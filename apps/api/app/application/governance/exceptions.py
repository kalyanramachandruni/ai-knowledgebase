from __future__ import annotations


class GovernanceApplicationError(Exception):
    pass


class ApprovalRequestNotFound(GovernanceApplicationError):
    pass


class NoPendingApprovalRequest(GovernanceApplicationError):
    pass
