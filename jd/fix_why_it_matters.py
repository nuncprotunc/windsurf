import re
import os

# Directory containing the YAML files
dir_path = r'd:\Code\windsurf\jd\cards_yaml'

# Pattern to match the why_it_matters section
pattern = r'^why_it_matters:(?:\s*\|)?(?:\s*"?\n?\s*)([\s\S]*?)(?=\n\w+:|\Z)'

# Function to fix the formatting
def fix_formatting(content):
    # Find the why_it_matters section
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return content  # No why_it_matters section found or already correct
    
    # Get the content of why_it_matters
    why_content = match.group(1).strip()
    
    # Create the new formatted section
    new_section = 'why_it_matters: |\n  ' + why_content + '\n'
    # Replace the old section with the new one
    return re.sub(pattern, new_section, content, flags=re.MULTILINE)

# Process each file
for filename in sorted(os.listdir(dir_path)):
    if not (filename.startswith('00') or filename.startswith('S00')) or not filename.endswith('.yml'):
        continue
        
    filepath = os.path.join(dir_path, filename)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if the file needs fixing
        if 'why_it_matters:' in content:
            new_content = fix_formatting(content)
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Fixed formatting in {filename}")
            else:
                print(f"{filename} already has correct formatting")
        else:
            print(f"{filename} does not contain a why_it_matters section")
            
    except Exception as e:
        print(f"Error processing {filename}: {str(e)}")
