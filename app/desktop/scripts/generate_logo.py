from PIL import Image, ImageDraw

def create_logo():
    # Canvas size
    width, height = 512, 512
    # Create image with transparent background
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background: Black rounded rectangle
    bg_color = (0, 0, 0, 255)
    radius = 128
    
    # Draw rounded rectangle (available in newer Pillow)
    draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=bg_color)

    # 2. Shape: The "S" polygon
    # Coordinates from SVG path
    points = [
        (146, 85),
        (366, 85),
        (416, 135),
        (416, 195),
        (376, 195),
        (206, 195),
        (396, 365),
        (396, 397),
        (366, 427),
        (146, 427),
        (96, 377),
        (96, 317),
        (136, 317),
        (306, 317),
        (116, 147),
        (116, 115),
        (146, 85)
    ]
    
    # Fill color: White/Light Gray to approximate the gradient
    shape_color = (255, 255, 255, 255) 
    
    draw.polygon(points, fill=shape_color)

    # Save
    output_path = "app/web/public/sage_logo.png"
    img.save(output_path)
    print(f"Logo generated at {output_path}")

if __name__ == "__main__":
    create_logo()
