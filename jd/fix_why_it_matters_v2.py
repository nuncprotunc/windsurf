import re
import os

# Directory containing the YAML files
dir_path = r'd:\Code\windsurf\jd\cards_yaml'

# Files that need fixing
files_to_fix = [
    '0001-torts-protected-interests-overview.yml',
    '0006-private-nuisance-unreasonableness-factors.yml',
    '0012-pure-economic-loss-relational.yml',
    '0014-breach-wrongs-act-s48-checklist.yml',
    '0015-causation-scope-interveners.yml'
]

# Process each file
for filename in files_to_fix:
    filepath = os.path.join(dir_path, filename)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the why_it_matters section
        pattern = r'^why_it_matters: \|\n(?:\s*>\n)?(\s+)([\s\S]*?)(?=\n\w+:|\Z)'
        match = re.search(pattern, content, re.MULTILINE)
        
        if match:
            indent = match.group(1)
            why_content = match.group(2)
            
            # Remove any leading '> ' or other special characters
            why_content = re.sub(r'^\s*>\s*', '', why_content, flags=re.MULTILINE)
            
            # Remove any backslashes and extra spaces
            why_content = re.sub(r'\\\s*\n\s*', ' ', why_content)
            
            # Create the new formatted section
            new_section = f'why_it_matters: |\n{indent}  {why_content.strip()}\n'
            # Replace the old section with the new one
            new_content = re.sub(pattern, new_section, content, flags=re.MULTILINE)
            
            # Write the fixed content back to the file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"Fixed formatting in {filename}")
        else:
            print(f"Could not find why_it_matters section in {filename}")
            
    except Exception as e:
        print(f"Error processing {filename}: {str(e)}")
