from pathlib import Path

from epmkit import EPMClient, month_end_refresh
from epmkit.exceptions import EPMJobFailed

with EPMClient("http://localhost:8000", "demo", "demo") as epm:
    print("rule:", epm.planning.run_rule("Plan1", "AggAll").wait(initial_delay=0.2))

    epm.planning.set_subvar("Plan1", "CurMonth", "Nov")
    print("subvars:", epm.planning.get_subvars("Plan1"))

    df = epm.planning.export_slice(
        "Plan1", "OEP_FS",
        pov={"Scenario": "Actual", "Year": "FY26"},
        rows={"Account": ["Revenue", "COGS", "Opex"]},
        cols={"Period": ["Jan", "Feb", "Mar"]},
    )
    print(df)

    try:
        epm.planning.run_rule("Plan1", "FailRule").wait(initial_delay=0.2)
    except EPMJobFailed as e:
        print("expected failure:", e)

    Path("actuals_nov.csv").write_text("Account,Period,Amount\nRevenue,Nov,125000\n")
    month_end_refresh(epm, "Plan1", "actuals_nov.csv", import_job="LoadActuals", rule="AggAll")
    print("files:", epm.files.list())
