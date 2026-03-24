import argparse
import os
import json
import sys
import random

def get_template(theme, layout, list_layouts=False):
    """
    Retrieves a template based on theme and layout type from a consolidated JSON file.
    """
    # Base directory for themes JSON
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates', 'layouts'))
    
    # Check if theme file exists, default to 'tech-dark.json' if not found
    theme_file = os.path.join(base_dir, f"{theme}.json")
    if not os.path.exists(theme_file):
        # Fallback to tech-dark if the requested theme file doesn't exist
        theme_file = os.path.join(base_dir, 'tech-dark.json')
        # Update theme name for display purposes if falling back? 
        # Actually, let's keep the requested theme name but load tech-dark content.
        # But if the user asked for a non-existent theme, we should probably warn them or just use tech-dark.
    
    try:
        with open(theme_file, 'r', encoding='utf-8') as f:
            theme_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Theme file not found for '{theme}' and fallback failed.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in theme file '{theme_file}'.")
        sys.exit(1)

    if list_layouts:
        layouts = sorted(theme_data.keys())
        print(f"Available layouts for theme '{theme}': {', '.join(layouts)}")
        return

    # Check layout
    if layout not in theme_data:
        print(f"Error: Layout '{layout}' not found in theme '{theme}'.")
        layouts = sorted(theme_data.keys())
        print(f"Available layouts: {', '.join(layouts)}")
        sys.exit(1)

    variants = theme_data[layout]
    
    if not variants:
        print(f"Error: No templates found for layout '{layout}'.")
        sys.exit(1)
        
    # Shuffle and select up to 3 variants
    random.shuffle(variants)
    selected_variants = variants[:3]
        
    # Return selected variants so the Agent can choose or see them
    output = []
    output.append(f"Found {len(selected_variants)} templates (selected from {len(variants)}) for Theme: {theme}, Layout: {layout}\n")
    
    for i, variant in enumerate(selected_variants):
        filename = f"variant_{i+1}"
        content = variant
        output.append(f"--- VARIANT: {filename} ---")
        output.append(content)
        output.append("\n")
            
    print("\n".join(output))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get a PPT XML template.")
    parser.add_argument("--theme", default="tech-dark", help="Theme name (e.g., tech-dark)")
    parser.add_argument("--layout", help="Layout type (e.g., cover, content_split, content_cards)")
    parser.add_argument("--list", action="store_true", help="List available layouts")

    args = parser.parse_args()
    
    if args.list:
        get_template(args.theme, None, list_layouts=True)
    elif args.layout:
        get_template(args.theme, args.layout)
    else:
        print("Error: --layout is required unless --list is specified.")
        sys.exit(1)
