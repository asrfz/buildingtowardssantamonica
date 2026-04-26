"""uAgents batch registration policy that skips Almanac HTTP (local bureau only)."""

from uagents_core.identity import Identity
from uagents_core.registration import BatchRegistrationPolicy
from uagents_core.types import AgentInfo


class AlmanacRegistrationSkipped(BatchRegistrationPolicy):
    """No-op: same-process agents still use dispatcher-based local delivery."""

    async def register(self) -> None:
        return

    def add_agent(self, agent_info: AgentInfo, identity: Identity) -> None:
        return
