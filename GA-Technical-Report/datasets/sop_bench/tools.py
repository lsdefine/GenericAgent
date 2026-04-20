# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""Order Fulfillment Tools - Simulated e-commerce order processing tools."""

from typing import Dict, List, Union, Optional, Any
import json
import os
import pandas as pd


class OrderFulfillmentManager:
    """Manager class for order fulfillment tools."""
    
    DATASET_CSV_FILE = "data.csv"
    TOOLSPEC_JSON_FILE = "toolspecs.json"
    
    # Simulated inventory database
    INVENTORY_DB = {
        "PROD001": {"name": "Wireless Headphones", "stock": 150, "reorder_level": 20},
        "PROD002": {"name": "USB-C Cable", "stock": 500, "reorder_level": 100},
        "PROD003": {"name": "Laptop Stand", "stock": 5, "reorder_level": 10},
        "PROD004": {"name": "Mechanical Keyboard", "stock": 0, "reorder_level": 15},
        "PROD005": {"name": "Monitor Arm", "stock": 75, "reorder_level": 25},
        "PROD006": {"name": "Webcam HD", "stock": 200, "reorder_level": 30},
        "PROD007": {"name": "Mouse Pad XL", "stock": 1000, "reorder_level": 200},
        "PROD008": {"name": "Phone Charger", "stock": 3, "reorder_level": 50},
        "PROD009": {"name": "Bluetooth Speaker", "stock": 0, "reorder_level": 20},
        "PROD010": {"name": "Smart Watch", "stock": 45, "reorder_level": 15},
    }
    
    # Simulated customer database
    CUSTOMER_DB = {
        "CUST001": {"name": "John Smith", "tier": "gold", "status": "active", "total_orders": 45, "fraud_score": 0.02},
        "CUST002": {"name": "Jane Doe", "tier": "platinum", "status": "active", "total_orders": 150, "fraud_score": 0.01},
        "CUST003": {"name": "Bob Wilson", "tier": "bronze", "status": "active", "total_orders": 3, "fraud_score": 0.15},
        "CUST004": {"name": "Alice Brown", "tier": "silver", "status": "review", "total_orders": 20, "fraud_score": 0.35},
        "CUST005": {"name": "Charlie Davis", "tier": "bronze", "status": "blocked", "total_orders": 5, "fraud_score": 0.85},
        "CUST006": {"name": "Emma Johnson", "tier": "gold", "status": "active", "total_orders": 78, "fraud_score": 0.03},
        "CUST007": {"name": "David Lee", "tier": "silver", "status": "active", "total_orders": 25, "fraud_score": 0.08},
        "CUST008": {"name": "Sarah Miller", "tier": "platinum", "status": "active", "total_orders": 200, "fraud_score": 0.01},
        "CUST009": {"name": "Mike Garcia", "tier": "bronze", "status": "active", "total_orders": 8, "fraud_score": 0.12},
        "CUST010": {"name": "Lisa Anderson", "tier": "gold", "status": "review", "total_orders": 55, "fraud_score": 0.25},
    }
    
    # Shipping rates by zip prefix and speed
    SHIPPING_RATES = {
        "standard": {"base": 5.99, "per_lb": 0.50, "days_min": 5, "days_max": 7},
        "express": {"base": 12.99, "per_lb": 1.00, "days_min": 2, "days_max": 3},
        "overnight": {"base": 24.99, "per_lb": 2.00, "days_min": 1, "days_max": 1},
    }
    
    # Remote zip prefixes (higher shipping costs)
    REMOTE_ZIPS = ["995", "996", "997", "998", "999", "006", "007", "008", "009"]

    def __init__(self):
        """Initialize the OrderFulfillmentManager."""
        self.dataset_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), self.DATASET_CSV_FILE
        )
        print(f"Dataset file path: {self.dataset_file_path}")
        
        self.toolspec_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), self.TOOLSPEC_JSON_FILE
        )
        print(f"Toolspec file path: {self.toolspec_file_path}")
        
        with open(self.toolspec_file_path, "r") as fr:
            toolspec_json = json.load(fr)
        self.tool_config = {"tools": toolspec_json}

    def check_inventory(self, product_id: str, quantity_requested: int) -> Dict[str, Any]:
        """
        Check inventory status for a product.
        
        Args:
            product_id: Product identifier (e.g., PROD001)
            quantity_requested: Number of units requested
            
        Returns:
            Dictionary with inventory status and available quantity
        """
        product_id = str(product_id).upper()
        quantity_requested = int(quantity_requested)
        
        if product_id not in self.INVENTORY_DB:
            return {
                "inventory_status": "product_not_found",
                "available_quantity": 0,
                "can_fulfill": False,
                "message": f"Product {product_id} not found in catalog"
            }
        
        product = self.INVENTORY_DB[product_id]
        available = product["stock"]
        
        if available == 0:
            status = "out_of_stock"
            can_fulfill = False
        elif available < quantity_requested:
            status = "insufficient_stock"
            can_fulfill = False
        elif available <= product["reorder_level"]:
            status = "low_stock"
            can_fulfill = True
        else:
            status = "in_stock"
            can_fulfill = True
        
        return {
            "inventory_status": status,
            "available_quantity": available,
            "quantity_requested": quantity_requested,
            "can_fulfill": can_fulfill,
            "product_name": product["name"]
        }

    def validate_customer(self, customer_id: str, order_total: float) -> Dict[str, Any]:
        """
        Validate customer account and check for fraud indicators.
        
        Args:
            customer_id: Customer identifier (e.g., CUST001)
            order_total: Total order value in dollars
            
        Returns:
            Dictionary with customer validation status
        """
        customer_id = str(customer_id).upper()
        order_total = float(order_total)
        
        if customer_id not in self.CUSTOMER_DB:
            return {
                "customer_status": "unknown",
                "customer_tier": "none",
                "approved": False,
                "message": f"Customer {customer_id} not found"
            }
        
        customer = self.CUSTOMER_DB[customer_id]
        
        # Blocked customers are rejected
        if customer["status"] == "blocked":
            return {
                "customer_status": "blocked",
                "customer_tier": customer["tier"],
                "approved": False,
                "message": "Customer account is blocked"
            }
        
        # High fraud score triggers review
        if customer["fraud_score"] > 0.3:
            return {
                "customer_status": "review_required",
                "customer_tier": customer["tier"],
                "approved": False,
                "fraud_score": customer["fraud_score"],
                "message": "Order flagged for fraud review"
            }
        
        # Large orders from new customers need review
        if customer["total_orders"] < 5 and order_total > 500:
            return {
                "customer_status": "review_required",
                "customer_tier": customer["tier"],
                "approved": False,
                "message": "Large order from new customer requires review"
            }
        
        # Otherwise approved
        return {
            "customer_status": "approved",
            "customer_tier": customer["tier"],
            "approved": True,
            "customer_name": customer["name"],
            "total_orders": customer["total_orders"]
        }

    def calculate_shipping(self, destination_zip: str, package_weight: float, shipping_speed: str) -> Dict[str, Any]:
        """
        Calculate shipping cost and delivery estimate.
        
        Args:
            destination_zip: Destination ZIP code (5 digits)
            package_weight: Package weight in pounds
            shipping_speed: One of 'standard', 'express', 'overnight'
            
        Returns:
            Dictionary with shipping cost and delivery estimate
        """
        destination_zip = str(destination_zip).zfill(5)[:5]
        package_weight = float(package_weight)
        shipping_speed = str(shipping_speed).lower()
        
        if shipping_speed not in self.SHIPPING_RATES:
            return {
                "shipping_cost": 0,
                "delivery_days": 0,
                "success": False,
                "message": f"Invalid shipping speed: {shipping_speed}. Use standard, express, or overnight."
            }
        
        rates = self.SHIPPING_RATES[shipping_speed]
        base_cost = rates["base"] + (package_weight * rates["per_lb"])
        
        # Apply remote area surcharge
        is_remote = destination_zip[:3] in self.REMOTE_ZIPS
        if is_remote:
            base_cost *= 1.5
            delivery_days = rates["days_max"] + 2
        else:
            delivery_days = rates["days_min"]
        
        return {
            "shipping_cost": round(base_cost, 2),
            "delivery_days": delivery_days,
            "shipping_speed": shipping_speed,
            "is_remote_area": is_remote,
            "success": True
        }

    def make_fulfillment_decision(
        self,
        inventory_status: str,
        customer_status: str,
        shipping_cost: float,
        order_priority: str
    ) -> Dict[str, Any]:
        """
        Make final fulfillment decision based on all inputs.
        
        Args:
            inventory_status: From check_inventory (in_stock, low_stock, out_of_stock, etc.)
            customer_status: From validate_customer (approved, blocked, review_required)
            shipping_cost: From calculate_shipping
            order_priority: Order priority level (normal, high, urgent)
            
        Returns:
            Dictionary with fulfillment decision
        """
        inventory_status = str(inventory_status).lower()
        customer_status = str(customer_status).lower()
        shipping_cost = float(shipping_cost)
        order_priority = str(order_priority).lower()
        
        # Customer blocked = reject
        if customer_status == "blocked":
            return {
                "decision": "reject",
                "reason": "Customer account is blocked",
                "action_required": "none"
            }
        
        # Customer needs review
        if customer_status == "review_required":
            return {
                "decision": "manual_review",
                "reason": "Customer requires manual review",
                "action_required": "fraud_team_review"
            }
        
        # Out of stock
        if inventory_status in ["out_of_stock", "product_not_found"]:
            return {
                "decision": "backorder",
                "reason": "Product not available",
                "action_required": "notify_customer_backorder"
            }
        
        # Insufficient stock
        if inventory_status == "insufficient_stock":
            return {
                "decision": "backorder",
                "reason": "Insufficient inventory for requested quantity",
                "action_required": "partial_or_backorder"
            }
        
        # In stock + approved customer
        if customer_status == "approved":
            if order_priority == "urgent" or inventory_status == "in_stock":
                return {
                    "decision": "fulfill_immediately",
                    "reason": "Order approved for immediate fulfillment",
                    "action_required": "ship_today",
                    "shipping_cost": shipping_cost
                }
            elif inventory_status == "low_stock":
                return {
                    "decision": "fulfill_delayed",
                    "reason": "Low stock - scheduling for batch fulfillment",
                    "action_required": "schedule_shipment",
                    "shipping_cost": shipping_cost
                }
        
        # Default fallback
        return {
            "decision": "manual_review",
            "reason": "Unable to automatically determine fulfillment path",
            "action_required": "operations_review"
        }

    def process_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        """
        Routes tool calls to appropriate methods.
        
        Parameters:
        -----------
        tool_name : str
            Name of the tool to execute
        tool_input : Dict[str, Any]
            Input parameters for the tool
            
        Returns:
        --------
        Any
            Tool execution results
            
        Raises:
        -------
        ValueError
            If tool_name is invalid
        """
        if tool_name == "check_inventory":
            return self.check_inventory(**tool_input)
        elif tool_name == "validate_customer":
            return self.validate_customer(**tool_input)
        elif tool_name == "calculate_shipping":
            return self.calculate_shipping(**tool_input)
        elif tool_name == "make_fulfillment_decision":
            return self.make_fulfillment_decision(**tool_input)
        else:
            raise ValueError(f"Invalid tool_name: {tool_name}")


if __name__ == "__main__":
    # Initialize manager
    manager = OrderFulfillmentManager()
    
    # Test tools
    print("\n--- Testing check_inventory ---")
    result = manager.check_inventory("PROD001", 2)
    print(result)
    
    print("\n--- Testing validate_customer ---")
    result = manager.validate_customer("CUST001", 159.98)
    print(result)
    
    print("\n--- Testing calculate_shipping ---")
    result = manager.calculate_shipping("98101", 1.5, "standard")
    print(result)
    
    print("\n--- Testing make_fulfillment_decision ---")
    result = manager.make_fulfillment_decision("in_stock", "approved", 6.74, "normal")
    print(result)
