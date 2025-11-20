import asyncio
import os
import sys
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.templating import Jinja2Templates
from backend.app.services.pdf_service import PDFService

async def generate_examples():
    """Generates example PDF invoice and order summary."""
    # The PDFService expects to be run from within the app's context,
    # so we need to make sure paths are set up correctly.
    # The script is run from the project root.
    template_dir = "backend/app/templates"
    templates = Jinja2Templates(directory=template_dir)
    
    # Instantiate the PDF service
    pdf_service = PDFService(template_renderer=templates)

    # Mock data for the PDF templates
    customer_data = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "address": "123 Main St, Anytown, USA 12345"
    }

    order_items_data = [
        {
            "name": "Laptop Pro",
            "quantity": 1,
            "unit_price": 1200.00,
            "total_price": 1200.00,
            "image_url": "static/img/laptop.png"
        },
        {
            "name": "Wireless Mouse",
            "quantity": 1,
            "unit_price": 75.50,
            "total_price": 75.50,
            "image_url": "static/img/mouse.png"
        },
        {
            "name": "USB-C Hub",
            "quantity": 2,
            "unit_price": 45.00,
            "total_price": 90.00,
            "image_url": "static/img/usb_hub.png"
        }
    ]

    subtotal = sum(item['total_price'] for item in order_items_data)
    tax = subtotal * 0.07
    total = subtotal + tax

    order_data = {
        "order_number": "ORD123456",
        "order_date": datetime.now().strftime("%Y-%m-%d"),
        "subtotal": subtotal,
        "tax": tax,
        "total": total
    }

    # Prepare contexts
    invoice_context = {
        "order": order_data,
        "customer": customer_data,
        "items": order_items_data
    }
    
    order_summary_context = {
        "order": order_data,
        "customer": customer_data,
        "items": order_items_data
    }

    # Generate PDFs
    print("Generating example invoice...")
    invoice_path = await pdf_service.render_pdf(
        template_name="pdf/invoice.html",
        context=invoice_context,
        output_name="example_invoice.pdf"
    )
    print(f"Invoice saved to: {invoice_path}")

    print("Generating example order summary...")
    order_summary_path = await pdf_service.render_pdf(
        template_name="pdf/order_summary.html",
        context=order_summary_context,
        output_name="example_order_summary.pdf"
    )
    print(f"Order summary saved to: {order_summary_path}")

if __name__ == "__main__":
    asyncio.run(generate_examples())
