import yaml
import re
from pathlib import Path

def clean_content(content):
    # Remove extra newlines and spaces
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r' {2,}', ' ', content)
    # Fix broken YAML syntax
    content = content.replace("` ` `", "```")  # Fix broken code block markers
    # Fix any other common formatting issues
    return content.strip()

def reformat_card(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Clean the content
        cleaned_content = clean_content(content)
        
        # Parse the YAML
        card = yaml.safe_load(cleaned_content)
        
        # Rebuild the card with clean structure
        formatted_card = {
            'front': card.get('front', '').strip(),
            'back': card.get('back', '').strip(),
            'why_it_matters': card.get('why_it_matters', '').strip(),
            'mnemonic': card.get('mnemonic', '').strip(),
            'diagram': card.get('diagram', '').strip(),
            'tripwires': card.get('tripwires', []),
            'anchors': card.get('anchors', {}),
            'reading_level': card.get('reading_level', 'Plain English (JD)'),
            'tags': card.get('tags', []),
            'keywords': card.get('keywords', [])
        }
        
        # Ensure anchors has the right structure
        if 'anchors' not in formatted_card or not isinstance(formatted_card['anchors'], dict):
            formatted_card['anchors'] = {}
        if 'cases' not in formatted_card['anchors']:
            formatted_card['anchors']['cases'] = []
        if 'statutes' not in formatted_card['anchors']:
            formatted_card['anchors']['statutes'] = []
        
        # Write back the cleaned file
        with open(filepath, 'w', encoding='utf-8') as f:
            # Write front matter
            front_content = yaml.dump(formatted_card['front'], default_style='"').strip()
            f.write(f'front: {front_content}\n')
            
            # Write back with proper formatting
            f.write('back: |\n')
            for line in formatted_card['back'].split('\n'):
                f.write(f'  {line}\n')
            
            # Write why_it_matters
            f.write('\nwhy_it_matters: |\n')
            for line in formatted_card['why_it_matters'].split('\n'):
                f.write(f'  {line}\n')
            
            # Write mnemonic
            f.write('\nmnemonic: ' + formatted_card['mnemonic'] + '\n')
            
            # Write diagram
            f.write('\ndiagram: |\n')
            for line in formatted_card['diagram'].split('\n'):
                f.write(f'  {line}\n')
            
            # Write tripwires
            f.write('\ntripwires:\n')
            for item in formatted_card['tripwires']:
                if isinstance(item, str):
                    f.write(f'  - "{item}"\n')
            
            # Write anchors
            f.write('\nanchors:\n')
            f.write('  cases:\n')
            for case in formatted_card['anchors'].get('cases', []):
                if isinstance(case, dict):
                    f.write('    - name: ' + case.get('name', '') + '\n')
                    f.write('      citation: ' + case.get('citation', '') + '\n')
                    f.write('      court: ' + case.get('court', '') + '\n')
                    if 'pinpoints' in case:
                        f.write('      pinpoints: "' + case['pinpoints'] + '"\n')
                    if 'notes' in case:
                        f.write('      notes: ' + case['notes'] + '\n')
                elif isinstance(case, str):
                    # Handle simple string format
                    f.write('    - ' + case + '\n')
            f.write('  statutes:\n')
            for statute in formatted_card['anchors'].get('statutes', []):
                if isinstance(statute, dict):
                    f.write('    - name: ' + statute.get('name', '') + '\n')
                    f.write('      provisions:\n')
                    for prov in statute.get('provisions', []):
                        f.write(f'        - {prov}\n')
                else:
                    f.write(f'    - {statute}\n')
            
            # Write reading level
            f.write('\nreading_level: ' + formatted_card['reading_level'] + '\n')
            
            # Write tags
            f.write('\ntags:\n')
            for tag in formatted_card.get('tags', []):
                f.write(f'  - {tag}\n')
            
            # Write keywords
            f.write('\nkeywords:\n')
            for kw in formatted_card.get('keywords', []):
                f.write(f'  - {kw}\n')
        
        print(f"Formatted {filepath.name}")
        
    except Exception as e:
        print(f"Error processing {filepath.name}: {str(e)}")

def main():
    cards_dir = Path(r'd:\Code\windsurf\jd\cards_yaml')
    
    # Process all YAML files except the exemplars
    exemplars = [
        '0001-torts-protected-interests-overview.yml',
        '0002-duty-existence-vs-scope-updated.yml',
        '0016-defences-loss-allocation-volenti-obvious-risk-cn.yml'
    ]
    
    for filepath in sorted(cards_dir.glob('*.yml')):
        if filepath.name not in exemplars:
            print(f"Processing {filepath.name}...")
            reformat_card(filepath)
    
    print("\nFormatting complete!")

if __name__ == "__main__":
    main()
