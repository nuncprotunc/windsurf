"""Schema validation for flashcards."""
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    template: Optional[str] = None

class SchemaValidator:
    def __init__(self, policy_path: str):
        """Initialize with path to the consolidated policy YAML file."""
        self.policy = self._load_yaml(policy_path)
        self.schema = self.policy.get('schema', {})
        self.rules = self.policy.get('validation_rules', {})
        self.autofix = self.policy.get('autofix', {})
    
    def _load_yaml(self, path: str) -> Dict:
        """Load a YAML file."""
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def validate_card(self, card_data: Dict) -> ValidationResult:
        """Validate a flashcard against the policy."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            template=card_data.get('template', 'concept')
        )
        
        # Check required fields
        required = self.schema.get('required_fields', [])
        for field in required:
            if field not in card_data or not card_data[field]:
                result.errors.append(f"Missing required field: {field}")
        
        # Apply validation rules
        self._apply_validation_rules(card_data, result)
        
        # Check word counts
        self._check_word_counts(card_data, result)
        
        # Check if any errors were found
        result.is_valid = not bool(result.errors)
            
        return result
    
    def _apply_validation_rules(self, card_data: Dict, result: ValidationResult) -> None:
        """Apply all enabled validation rules."""
        for rule_id, rule in self.rules.items():
            if not rule.get('enabled', False):
                continue
            if rule_id == 'F001':
                self._validate_required_fields(card_data, result)
            # Add more rule validations as needed
    
    def _validate_required_fields(self, card_data: Dict, result: ValidationResult) -> None:
        required = self.schema.get('required_fields', [])
        for field in required:
            if field not in card_data or not card_data[field]:
                result.errors.append(f"F001: {field} is required")
    
    def _check_word_counts(self, card_data: Dict, result: ValidationResult) -> None:
        """Check that word counts are within limits."""
        # Get word limits from policy
        front_max = self.policy.get('front', {}).get('max_words', 30)
        back_min = self.policy.get('back', {}).get('min_words', 50)
        back_max = self.policy.get('back', {}).get('max_words', 260)
        
        # Front text check
        if 'front' in card_data:
            words = len(card_data['front'].split())
            if words > front_max:
                result.errors.append(f"Front exceeds {front_max} words")
        
        # Back text check
        if 'back' in card_data:
            words = len(card_data['back'].split())
            if words < back_min:
                result.errors.append(f"Back has fewer than {back_min} words")
            elif words > back_max:
                result.errors.append(f"Back exceeds {back_max} words")
    
    def _check_authorities(self, card_data: Dict, result: ValidationResult) -> None:
        """Validate legal authorities."""
        if 'authorities' not in card_data:
            return
            
        authorities = card_data['authorities']
        max_auth = self.policy.get('authorities', {}).get('max_unique_authorities_in_back', 8)
        
        if len(authorities) > max_auth:
            result.warnings.append(
                f"Found {len(authorities)} authorities, "
                f"recommended max is {max_auth}"
            )
