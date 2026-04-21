import sys; sys.path.insert(0,'.')
from io_analysis.data.loader import load_all_flows
from io_analysis.analysis.analyzer import run_analysis
from io_analysis.config import Config
from pathlib import Path

cfg = Config()
cfg.data_path = Path(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle\Results")
flows = load_all_flows(cfg)
result = run_analysis(flows, cfg)

s = result.overall_summary
tp  = s['total_pass']
tf  = s['total_fail']
tot = s['total_measurements']
pr  = s['overall_pass_rate']
print(f'Total measurements : {tot}')
print(f'Pass               : {tp}')
print(f'Fail               : {tf}')
print(f'Pass rate          : {tp}/{tot} = {pr:.2f}%')
print()
print('Failing parameters (contributing to fail count):')
for (flow, param), st in sorted(result.parameter_stats.items()):
    if st.fail_count > 0:
        print(f'  {flow}/{param:30s}  pass={st.pass_count:6d}  fail={st.fail_count:6d}  ({st.pass_rate:.1f}%)')
