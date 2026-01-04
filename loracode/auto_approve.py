"""
Auto-Approve System for LoraCode CLI.

This module provides category-based automatic approval functionality,
allowing users to configure automatic approval or rejection for specific
operation categories.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple, List


class ApprovalCategory(Enum):
    """Categories of operations that require user approval."""
    
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
        """
        Convert string to ApprovalCategory.
        
        Returns OTHER if the value is not a valid category name.
        """
        try:
            return cls(value.lower())
        except ValueError:
            return cls.OTHER
    
    @classmethod
    def all_categories(cls) -> list[str]:
        """Return all category names as strings (excluding OTHER)."""
        return [c.value for c in cls if c != cls.OTHER]


class ApprovalRule(Enum):
    """Rules that can be applied to approval categories."""
    
    ALWAYS = "always"  # Automatically approve
    NEVER = "never"    # Automatically reject
    ASK = "ask"        # Prompt user for confirmation (default)
    
    @classmethod
    def from_string(cls, value: str) -> "ApprovalRule":
        """
        Convert string to ApprovalRule.
        
        Returns ASK if the value is not a valid rule name.
        """
        try:
            return cls(value.lower())
        except ValueError:
            return cls.ASK


@dataclass
class ApprovalDecision:
    """Record of an approval decision."""
    
    timestamp: datetime
    category: ApprovalCategory
    rule_applied: ApprovalRule
    subject: str
    question: str
    result: bool  # True = approved, False = rejected
    auto_decided: bool  # True if decided by rule, False if user prompted


@dataclass
class AutoApproveManager:
    """
    Manager class for auto-approval rules and history.
    
    Handles setting/getting rules for categories and recording approval decisions.
    """
    
    rules: dict = None
    history: list = None
    max_history: int = 100
    
    def __post_init__(self):
        """Initialize rules dict with default ASK for all categories."""
        if self.rules is None:
            self.rules = {}
        if self.history is None:
            self.history = []
        
        # Set default ASK rule for all categories
        for category in ApprovalCategory:
            if category not in self.rules:
                self.rules[category] = ApprovalRule.ASK
    
    def set_rule(self, category: ApprovalCategory, rule: ApprovalRule) -> None:
        """Set approval rule for a category."""
        self.rules[category] = rule
    
    def get_rule(self, category: ApprovalCategory) -> ApprovalRule:
        """Get approval rule for a category."""
        return self.rules.get(category, ApprovalRule.ASK)
    
    def should_auto_decide(self, category: ApprovalCategory) -> tuple[bool, Optional[bool]]:
        """
        Check if category should be auto-decided.
        
        Returns:
            tuple[bool, Optional[bool]]: (should_auto_decide, decision)
            - ALWAYS → (True, True)
            - NEVER → (True, False)
            - ASK → (False, None)
        """
        rule = self.get_rule(category)
        if rule == ApprovalRule.ALWAYS:
            return (True, True)
        elif rule == ApprovalRule.NEVER:
            return (True, False)
        return (False, None)
    
    def set_all(self, rule: ApprovalRule) -> None:
        """Set all categories to the same rule."""
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
        """Record an approval decision in history."""
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
        """Get recent approval decisions."""
        return self.history[-limit:]
    
    def to_dict(self) -> dict:
        """
        Serialize rules to dictionary for config file.
        
        Only serializes non-default rules (rules that are not ASK).
        """
        return {
            cat.value: rule.value 
            for cat, rule in self.rules.items()
            if rule != ApprovalRule.ASK  # Only save non-default rules
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AutoApproveManager":
        """
        Create manager from config dictionary.
        
        Args:
            data: Dictionary with category names as keys and rule names as values.
            
        Returns:
            AutoApproveManager with rules set from the dictionary.
        """
        manager = cls()
        for cat_str, rule_str in data.items():
            category = ApprovalCategory.from_string(cat_str)
            rule = ApprovalRule.from_string(rule_str)
            if category != ApprovalCategory.OTHER:
                manager.set_rule(category, rule)
        return manager
    
    def get_status_display(self) -> str:
        """
        Get formatted status string for display.
        
        Returns a formatted string showing the current approval settings
        for all categories (excluding OTHER).
        """
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
    """
    Parse a comma-separated list of category names.
    
    Args:
        categories_str: Comma-separated category names or None.
        
    Returns:
        List of category name strings (lowercase, stripped).
    """
    if not categories_str:
        return []
    
    return [cat.strip().lower() for cat in categories_str.split(",") if cat.strip()]


def validate_category_names(category_names: List[str]) -> Tuple[List[str], List[str]]:
    """
    Validate a list of category names.
    
    Args:
        category_names: List of category name strings.
        
    Returns:
        Tuple of (valid_categories, invalid_categories).
    """
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
    """
    Check for conflicts between approve and reject lists.
    
    Args:
        approve_list: List of categories to auto-approve.
        reject_list: List of categories to auto-reject.
        
    Returns:
        List of conflicting category names (empty if no conflicts).
    """
    # Handle 'all' special case
    approve_set = set(approve_list)
    reject_set = set(reject_list)
    
    # If both have 'all', that's a conflict
    if "all" in approve_set and "all" in reject_set:
        return ["all"]
    
    # If one has 'all', expand it to all categories for conflict check
    all_categories = set(ApprovalCategory.all_categories())
    
    if "all" in approve_set:
        approve_set = all_categories
    else:
        approve_set.discard("all")
    
    if "all" in reject_set:
        reject_set = all_categories
    else:
        reject_set.discard("all")
    
    # Find intersection (conflicts)
    conflicts = approve_set & reject_set
    return sorted(list(conflicts))


def validate_auto_approve_args(
    auto_approve: Optional[str], auto_reject: Optional[str]
) -> Tuple[bool, Optional[str], List[str], List[str]]:
    """
    Validate --auto-approve and --auto-reject CLI arguments.
    
    Args:
        auto_approve: Value of --auto-approve argument.
        auto_reject: Value of --auto-reject argument.
        
    Returns:
        Tuple of (is_valid, error_message, approve_categories, reject_categories).
        If is_valid is False, error_message contains the error description.
    """
    approve_list = parse_category_list(auto_approve)
    reject_list = parse_category_list(auto_reject)
    
    # Validate category names
    valid_approve, invalid_approve = validate_category_names(approve_list)
    valid_reject, invalid_reject = validate_category_names(reject_list)
    
    # Check for invalid category names
    all_invalid = invalid_approve + invalid_reject
    if all_invalid:
        return (
            False,
            f"Invalid category names: {', '.join(all_invalid)}. "
            f"Valid categories: {', '.join(ApprovalCategory.all_categories())}, all",
            [],
            []
        )
    
    # Check for conflicts
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
    """
    Apply CLI arguments to an AutoApproveManager.
    
    Args:
        manager: The AutoApproveManager to configure.
        approve_categories: List of categories to set to ALWAYS.
        reject_categories: List of categories to set to NEVER.
        yes_always: If True, set all categories to ALWAYS (backward compatibility).
    """
    # Handle --yes-always backward compatibility
    if yes_always:
        manager.set_all(ApprovalRule.ALWAYS)
        return
    
    # Handle 'all' in approve list
    if "all" in approve_categories:
        manager.set_all(ApprovalRule.ALWAYS)
        return
    
    # Handle 'all' in reject list
    if "all" in reject_categories:
        manager.set_all(ApprovalRule.NEVER)
        return
    
    # Apply individual category rules
    for cat_name in approve_categories:
        category = ApprovalCategory.from_string(cat_name)
        if category != ApprovalCategory.OTHER:
            manager.set_rule(category, ApprovalRule.ALWAYS)
    
    for cat_name in reject_categories:
        category = ApprovalCategory.from_string(cat_name)
        if category != ApprovalCategory.OTHER:
            manager.set_rule(category, ApprovalRule.NEVER)
