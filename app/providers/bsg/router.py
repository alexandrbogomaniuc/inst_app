from __future__ import annotations

from fastapi import APIRouter

# Top-level router with the /betsoft prefix
router = APIRouter(prefix="/betsoft", tags=["betsoft"])

# Import and mount each endpoint router
from .endpoints.authenticate import router as authenticate_router  # noqa: E402
from .endpoints.account import router as account_router            # noqa: E402
from .endpoints.balance import router as balance_router            # noqa: E402
from .endpoints.bet_result import router as bet_result_router      # noqa: E402
from .endpoints.refund_bet import router as refund_bet_router      # noqa: E402
from .endpoints.bonus_win import router as bonus_win_router        # noqa: E402
from .endpoints.bonus_release import router as bonus_release_router# noqa: E402

router.include_router(authenticate_router)
router.include_router(account_router)
router.include_router(balance_router)
router.include_router(bet_result_router)
router.include_router(refund_bet_router)
router.include_router(bonus_win_router)
router.include_router(bonus_release_router)
