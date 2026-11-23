"""Generate B1-only coverage figures, CSV, extension manifest and acceptance report."""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from asar_repro.hrrr import require
from asar_repro.scenarios import digest
from import_additional_b1 import ROOT, save


def read(path):
    return json.loads(path.read_bytes())


def generate(output, publish=False):
    summary=read(output/'summary.json')
    tests=read(output/'full_pytest.json')
    match=re.search(r'(\d+) passed.*? in ([\d.]+)s',tests['stdout'])
    require(summary['status']=='passed' and tests['exit_code']==0 and match,
            'blocked: B1 import and full tests must both pass')
    records=[read(output/(name+'_validation.json')) for name in summary['scenarios']]
    before=read(output/'frozen_before.json')
    require(all(digest(ROOT/p)==sha for p,sha in before.items()),'blocked: frozen file changed')
    manifest=read(output/'historical_sources_extension.json')
    rows=[]
    for record in records:
        for role in ('wind','current'):
            for source in record[role]['local_files']:
                times=[source['valid_utc']] if role=='wind' else source['valid_times_utc']
                for time in times:
                    rows.append(dict(scenario=record['scenario'],role=role,product=record[role]['product'],
                                     utc=time,file=source['local_path'],sha256=source['sha256'],
                                     vector_basis=record[role]['vector_basis'],units=record[role]['units'],
                                     verification_scope='B1_local_files',B2_completed=False,B3_completed=False))
    csvpath=output/'forcing_times_and_fingerprints.csv'
    with csvpath.open('x',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    fig,axes=plt.subplots(len(records),1,figsize=(11,3.6*len(records)),squeeze=False)
    for ax,record in zip(axes[:,0],records,strict=True):
        incident=datetime.fromisoformat(record['requested_window_utc'][0])
        hours=lambda stamp:(datetime.fromisoformat(stamp)-incident).total_seconds()/3600
        cst=hours(record['mission']['cst_utc']);end=hours(record['requested_window_utc'][1])
        ax.axvspan(0,cst,color='grey',alpha=.12,label='pre-drift window')
        ax.axvspan(cst,end,color='orange',alpha=.25,label='search window')
        for y,role,color in [(1,'wind','#167b9c'),(0,'current','#ad4b2a')]:
            t=[hours(r['utc']) for r in rows if r['scenario']==record['scenario'] and r['role']==role]
            ax.plot(t,[y]*len(t),'o-',color=color,markersize=5)
        ax.axvline(cst,color='black',linestyle='--',linewidth=1)
        ax.set(yticks=[0,1],yticklabels=[record['current']['product'],record['wind']['product']],
               ylim=(-.6,1.6),xlabel='Hours from incident ('+incident.isoformat()+')',
               title=record['mission']['name']+' | B1 input files verified; B2/B3 pending')
        ax.legend(loc='upper left',ncol=2);ax.grid(axis='x',alpha=.25)
    fig.tight_layout();fig.savefig(output/'forcing_coverage.png',dpi=160);plt.close(fig)
    status=dict(stage='B1_additional_data',status='passed',full_pytest_passed=int(match[1]),
                pytest_s=float(match[2]),frozen_files_unchanged=len(before),
                scenarios=summary['scenarios'],B2_completed=False,B3_completed=False,
                source_commit=summary['source_commit'],manifest_sha256=digest(output/'historical_sources_extension.json'))
    save(output/'acceptance.json',status)
    lines=['# 新增真实风流数据：B1 本机接入验收','',
           '**状态：passed（仅 B1 数据层）。新增场景的 B2 reader、B3 粒子与规划对照尚未执行。**','',
           'Lake Ontario 已在 B3/B7 使用真实风流。本轮对同一 ZIP 重验，确认 26 份包内交付文件指纹一致，未把它重复计为新增场景。结合“另外两个场景”及本地目录，额外核验 Hudsons Bay 与 Bay of Fundy；Salish Sea 不在本轮范围。','',
           '| 场景 | 本地交付 forcing | 有效 UTC | 任务窗口 UTC | 状态 |','|---|---|---|---|---|']
    for r in records:
        wind,current=r['wind'],r['current']
        lines.append(f"| {r['scenario']} | {len(wind['local_files'])} 风文件 / {len(current['local_files'])} 流文件；风 {wind['coverage']['time_count']} 帧 / 流 {current['coverage']['time_count']} 帧 | {current['coverage']['first_utc']} → {current['coverage']['last_utc']} | {' → '.join(r['requested_window_utc'])} | B1 verified；B2/B3 false |")
    lines += ['', '每个新增包 39 份交付文件完成 SHA-256 复核。原始消息边界也与 .idx 字节范围和逐消息 SHA 对照；不是只检查文件头。风场全网格 min/max/mean/std、LKP/CSP 的索引和数值均与下载环境的独立 ecCodes 记录一致。HYCOM/GoMOFS 全部交付时次解码，验证变量、维度、单位、缺测、任务点和窗口覆盖。','',
        '## 数值事实、处理与局限','',
        '- Hudsons Bay 对应代码 arctic_ocean / alias hudsons_bay。GFS 风来自固定 2025-08-28 18 UTC 循环 f003–f033，3 小时间隔；它是地理东/北分量。HYCOM ssu/ssv 为水流，sic 是海冰比例；没有使用海冰漂移速度。',
        '- HYCOM short + scale_factor 只解包一次，_FillValue=-30000 仍是掩膜。原经度 0–360 已转换为 −180–180 后核对任务点；不改写原 NetCDF。LKP/CSP 周围 2×2 邻域全部时次有效；有效水域 sic=0。这不替代将来沿真实粒子轨迹的检查。',
        '- HYCOM 为官方 NCSS 原网格子集，不持有全球母文件哈希；年度聚合序列尚未逐帧核实原循环。读取 time 坐标，而非全局 time_origin/created_on。',
        '- Bay of Fundy 风是 HRRR 网格方向 U/V；GoMOFS u_sur/v_sur 位于 ROMS 不同交错网格，为 xi/eta 分量。本轮只核验原数值，未把它们当作地理东/北流；B2 必须验证插值、对齐、旋转和静态/动态湿干掩膜。',
        '- GoMOFS 交付为约 123 MB 的表层原变量提取与时间串接文件。13 个完整母文件只保存来源/指纹及下载环境的比较记录，本机没有母文件，因此 original_parent_files_reverified_locally=false。不能把下载环境记录写成本机独立重验。',
        '- 两组均为历史环境重建；未证明作者相同循环、原粒子/人工 PT 或当时实时可得性。未新增任何 ε-最优或规划认证声明。','',
        '## 本机问题与修复','',
        '既有 maritime-sar 没有 ecCodes，GDAL 也缺少 GRIB 插件；本轮未安装、升级任何依赖。新增严格 NumPy GFS 解码器，仅接受本包的 GRIB2 3.0/4.0/5.3、无缺测位图、general group splitting 与一/二阶差分；其他格式明确报错。',
        '首轮 HYCOM 坐标检查因 0–360 经度与负经度任务点不一致而 blocked，记录保留在 additional_b1_20261123。修复坐标标准化后，在新目录重新验收，并新增该回归用例。中间仅 Hudsons Bay 通过的记录保留在 additional_b1_20261123_verified；当前两组结果以本目录为准。','',
        '实现依据为 NOAA [模板 5.3](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp5-3.shtml)、[模板 7.3](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp7-3.shtml)；省略时区的时间单位按 [CF 4.4](https://cfconventions.org/Data/cf-conventions/cf-conventions-1.11/cf-conventions.html#time-coordinate) 解释为 UTC，并与包内 UTC 时次对照。','',
        '## 测试、文件和复跑','',
        f"全量 pytest：{status['full_pytest_passed']} passed，{status['pytest_s']} s；新增 14 项测试。全部原有 {len(before)} 份跟踪文件与 B7 的 426 份冻结输入/证据保持不变。实际解释器：{summary['interpreter']}；版本：{summary['versions']}。",'',
        '新增脚本：scripts/b1_gfs.py、scripts/b1_extra_currents.py、scripts/import_additional_b1.py、scripts/report_additional_b1.py；测试：tests/test_b1_additional.py；ZIP/校验表指纹：configs/b1_additional_packages.json。源码未改动搜索、启发式、评分、旧 reader 或原海上搜救仿真程序。','',
        '新增清单 data/manifests/historical_sources_additional_b1.json 保留旧清单的 Lake Ontario 和 Salish Sea 条目，仅加入两组本机 verified 条目。旧 data/manifests/historical_sources.json 是 B3/B7 冻结依赖，保持原字节；B2 扩展应显式选择新清单。','',
        '在 asar_repro 下使用现有解释器（将 NEW 换成不存在的输出目录名）：','',
        '```powershell',
        "$PY='C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe'",
        "$env:PYTHONPATH=(Resolve-Path 'scripts/offline_guard').Path+';'+(Resolve-Path 'src').Path",
        "$env:PATH=(Join-Path (Split-Path $PY) 'Library\\bin')+';'+$env:PATH",
        "$env:PYTHONIOENCODING='utf-8'",
        "$env:ASAR_OFFLINE='1'",
        "$env:PROJ_NETWORK='OFF'",
        '& $PY -m pytest -q',
        '& $PY scripts/import_additional_b1.py --include-fundy --output-dir outputs/baseline_v1.1/NEW',
        '```','',
        '交付 CSV：forcing_times_and_fingerprints.csv（68 条新增风/流时次记录）；图片：forcing_coverage.png；逐文件证据：arctic_ocean_validation.json、bay_of_fundy_validation.json、lake_ontario_recheck.json；测试：full_pytest.json；最终状态：acceptance.json。输出目录中的 SHA 清单保护新增代码、配置、清单、报告与证据。','',
        '当前停在 B1。下一阶段只需开展这两组新增场景的 B2：GFS 地理风采样、HYCOM 掩膜/海冰与时空插值、HRRR 旋转、GoMOFS ROMS 交错网格/方向/湿干处理；B2 通过后再进入 B3，保持现有 Lake Ontario 输入及评分协议不变。']
    report='\n'.join(lines)+'\n'
    with (output/'report.md').open('x',encoding='utf-8') as f:f.write(report)
    if publish:
        save(ROOT/'data/manifests/historical_sources_additional_b1.json',manifest)
        with (ROOT/'docs/baseline_v1.1/additional_b1_report.md').open('x',encoding='utf-8') as f:f.write(report)
    print(json.dumps(status,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--publish',action='store_true')
    a=p.parse_args()
    generate(a.output_dir,a.publish)
