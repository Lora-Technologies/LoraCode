from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple, List


class ApprovalCategory(Enum):
    FILE_CREATE = "file_create"
    FILE_EDIT = "file_edit"
    SHELL_COMMAND = "shell_command"
    URL_ADD = "url_add"
    LINT_FIX = "lint_fix"
    TEST_FIX = "test_fix"
    GIT_REPO = "git_repo"
    ANALYTICS = "analytics"
    OTHER = "other"
    
    @classmethod
    def from_string(cls, value: str) -> "ApprovalCategory":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.OTHER
    
    @classmethod
    def all_categories(cls) -> list[str]:
        return [c.value for c in cls if c != cls.OTHER]


class ApprovalRule(Enum):
    
    ALWAYS = "always"  # Automatically approve
    NEVER = "never"    # Automatically reject
    ASK = "ask"        # Prompt user for confirmation (default)
    
    @classmethod
    def from_string(cls, value: str) -> "ApprovalRule":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.ASK


@dataclass
class ApprovalDecision:
    timestamp: datetime
    category: ApprovalCategory
    rule_applied: ApprovalRule
    subject: str
    question: str
    result: bool  # True = approved, False = rejected
    auto_decided: bool  # True if decided by rule, False if user prompted


@dataclass
class AutoApproveManager:
    rules: dict = None
    history: list = None
    max_history: int = 100
    
    def __post_init__(self):
        if self.rules is None:
            self.rules = {}
        if self.history is None:
            self.history = []
        
        # Set default ASK rule for all categories
        for category in ApprovalCategory:
            if category not in self.rules:
                self.rules[category] = ApprovalRule.ASK
    
    def set_rule(self, category: ApprovalCategory, rule: ApprovalRule) -> None:
        self.rules[category] = rule
    
    def get_rule(self, category: ApprovalCategory) -> ApprovalRule:
        return self.rules.get(category, ApprovalRule.ASK)
    
    def should_auto_decide(self, category: ApprovalCategory) -> tuple[bool, Optional[bool]]:
        rule = self.get_rule(category)
        if rule == ApprovalRule.ALWAYS:
            return (True, True)
        elif rule == ApprovalRule.NEVER:
            return (True, False)
        return (False, None)
    
    def set_all(self, rule: ApprovalRule) -> None:
        for category in ApprovalCategory:
            self.rules[category] = rule
    
    def record_decision(
        self,
        category: ApprovalCategory,
        subject: str,
        question: str,
        result: bool,
        auto_decided: bool
    ) -> None:
        decision = ApprovalDecision(
            timestamp=datetime.now(),
            category=category,
            rule_applied=self.get_rule(category),
            subject=subject,
            question=question,
            result=result,
            auto_decided=auto_decided
        )
        self.history.append(decision)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
    
    def get_history(self, limit: int = 20) -> list[ApprovalDecision]:
        return self.history[-limit:]
    
    def to_dict(self) -> dict:
        return {
            cat.value: rule.value 
            for cat, rule in self.rules.items()
            if rule != ApprovalRule.ASK  # Only save non-default rules
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AutoApproveManager":
        manager = cls()
        for cat_str, rule_str in data.items():
            category = ApprovalCategory.from_string(cat_str)
            rule = ApprovalRule.from_string(rule_str)
            if category != ApprovalCategory.OTHER:
                manager.set_rule(category, rule)
        return manager
    
    def get_status_display(self) -> str:
        lines = ["Auto-Approval Status:"]
        for category in ApprovalCategory:
            if category == ApprovalCategory.OTHER:
                continue
            rule = self.get_rule(category)
            if rule == ApprovalRule.ALWAYS:
                status = "✓"
            elif rule == ApprovalRule.NEVER:
                status = "✗"
            else:
                status = "?"
            lines.append(f"  {status} {category.value}: {rule.value}")
        return "\n".join(lines)


def parse_category_list(categories_str: Optional[str]) -> List[str]:
    if not categories_str:
        return []
    
    return [cat.strip().lower() for cat in categories_str.split(",") if cat.strip()]


def validate_category_names(category_names: List[str]) -> Tuple[List[str], List[str]]:
    valid_categories = ApprovalCategory.all_categories()
    valid = []
    invalid = []
    
    for name in category_names:
        if name == "all":
            valid.append(name)
        elif name in valid_categories:
            valid.append(name)
        else:
            invalid.append(name)
    
    return valid, invalid


def check_category_conflicts(
    approve_list: List[str], reject_list: List[str]
) -> List[str]:
    approve_set = set(approve_list)
    reject_set = set(reject_list)
    if "all" in approve_set and "all" in reject_set:
        return ["all"]
    all_categories = set(ApprovalCategory.all_categories())
    if "all" in approve_set:
        approve_set = all_categories
    else:
        approve_set.discard("all")
    
    if "all" in reject_set:
        reject_set = all_categories
    else:
        reject_set.discard("all")
    conflicts = approve_set & reject_set
    return sorted(list(conflicts))


def validate_auto_approve_args(
    auto_approve: Optional[str], auto_reject: Optional[str]
) -> Tuple[bool, Optional[str], List[str], List[str]]:
    approve_list = parse_category_list(auto_approve)
    reject_list = parse_category_list(auto_reject)
    valid_approve, invalid_approve = validate_category_names(approve_list)
    valid_reject, invalid_reject = validate_category_names(reject_list)
    all_invalid = invalid_approve + invalid_reject
    if all_invalid:
        return (
            False,
            f"Invalid category names: {', '.join(all_invalid)}. "
            f"Valid categories: {', '.join(ApprovalCategory.all_categories())}, all",
            [],
            []
        )
    conflicts = check_category_conflicts(valid_approve, valid_reject)
    if conflicts:
        return (
            False,
            f"Conflicting categories in --auto-approve and --auto-reject: {', '.join(conflicts)}",
            [],
            []
        )
    
    return (True, None, valid_approve, valid_reject)


def apply_auto_approve_args(
    manager: "AutoApproveManager",
    approve_categories: List[str],
    reject_categories: List[str],
    yes_always: bool = False
) -> None:
    if yes_always:
        manager.set_all(ApprovalRule.ALWAYS)
        return
    if "all" in approve_categories:
        manager.set_all(ApprovalRule.ALWAYS)
        return
    if "all" in reject_categories:
        manager.set_all(ApprovalRule.NEVER)
        return
    for cat_name in approve_categories:
        category = ApprovalCategory.from_string(cat_name)
        if category != ApprovalCategory.OTHER:
            manager.set_rule(category, ApprovalRule.ALWAYS)
    
    for cat_name in reject_categories:
        category = ApprovalCategory.from_string(cat_name)
        if category != ApprovalCategory.OTHER:
            manager.set_rule(category, ApprovalRule.NEVER)
