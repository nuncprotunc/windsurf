import yaml
import os
from pathlib import Path

def format_card(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            card = yaml.safe_load(f)
        
        # Ensure all required fields exist with proper formatting
        if 'front' not in card:
            card['front'] = ""
        if 'back' not in card:
            card['back'] = ""
        if 'why_it_matters' not in card:
            card['why_it_matters'] = ""
        if 'mnemonic' not in card:
            card['mnemonic'] = ""
        if 'diagram' not in card:
            card['diagram'] = ""
        if 'tripwires' not in card:
            card['tripwires'] = []
        if 'anchors' not in card:
            card['anchors'] = {'cases': [], 'statutes': []}
        if 'reading_level' not in card:
            card['reading_level'] = "Plain English (JD)"
        if 'tags' not in card:
            card['tags'] = []
        if 'keywords' not in card:
            card['keywords'] = []
        
        # Format the YAML with consistent style
        formatted_yaml = yaml.dump(
            card,
            default_flow_style=False,
            allow_unicode=True,
            width=1000,  # Prevent unwanted line breaks
            sort_keys=False  # Maintain original key order
        )
        
        # Clean up formatting
        formatted_yaml = formatted_yaml.replace("\n- ", "\n\n- ")  # Add space before list items
        formatted_yaml = formatted_yaml.replace("\n  - ", "\n  \n  - ")  # Add space before nested list items
        
        # Save the formatted file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(formatted_yaml)
            
    except Exception as e:
        print(f"Error processing {filepath}: {str(e)}")

def main():
    cards_dir = Path(r'd:\Code\windsurf\jd\cards_yaml')
    processed_files = [
        '0001-torts-protected-interests-overview.yml',
        '0002-duty-existence-vs-scope.yml',
        '0002-duty-existence-vs-scope-clean.yml',
        '0002-duty-existence-vs-scope-updated.yml',
        '0016-defences-loss-allocation-volenti-obvious-risk-cn.yml'
    ]
    
    for filepath in cards_dir.glob('*.yml'):
        if filepath.name not in processed_files:
            print(f"Formatting {filepath.name}...")
            format_card(filepath)
    
    print("Formatting complete!")

if __name__ == "__main__":
    main()
