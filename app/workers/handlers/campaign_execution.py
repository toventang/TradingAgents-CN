from typing import Dict, Any, Optional
import pandas as pd

from app.models.domain_task import TaskType
from app.services.domain_tasks.handler_registry import TaskContext, global_handler_registry
from app.services.campaigns.cycle_engine import CampaignCycleEngine


class CampaignTaskHandler:
    """异步 Campaign 周期调仓 Worker Handler"""

    def __init__(self, engine: Optional[CampaignCycleEngine] = None):
        self.engine = engine or CampaignCycleEngine()

    async def handle_task(self, context: TaskContext) -> Dict[str, Any]:
        params = context.task.payload or {}
        campaign_id = params.get("campaign_id")
        cycle_date = params.get("cycle_date")
        factors_data = params.get("factors_data", [])
        prices_data = params.get("current_prices", {})

        factors_df = pd.DataFrame(factors_data)
        if not factors_df.empty and "symbol" in factors_df.columns:
            factors_df.set_index("symbol", inplace=True)

        res = await self.engine.execute_cycle(
            campaign_id=campaign_id,
            cycle_date=cycle_date,
            factor_values_df=factors_df,
            current_prices=prices_data
        )

        return res.model_dump()


global_handler_registry.register(TaskType.CAMPAIGN_CYCLE_EXECUTION, CampaignTaskHandler().handle_task)
