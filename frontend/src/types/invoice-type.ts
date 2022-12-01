import {PricingUnit} from "./pricing-unit-type";

export interface InvoiceType {
  cost_due: string;
  cost_due_currency: string;
  id: string;
  issue_date: string;
  payment_status: string;
  line_items: LineItem[];
  customer: InvoiceCustomer;
  external_payment_obj_type: string;
}

export interface DraftInvoiceType {
  line_items: LineItem[];
  cost_due: string;
  cost_due_currency: string;
  cust_connected_to_payment_provider: boolean;
  org_connected_to_cust_payment_provider: boolean;
}

export interface BalanceAdjustments {
    amount: number;
    amount_currency: string;
    description: string;
    created: string;
    effective_at: string;
    expires_at: string;
    adjustment_id: string;
    customer_id: string;
    parent_adjustment_id: string;
    pricing_unit: PricingUnit;
    status: "active" | "inactive";
}

interface InvoiceCustomer {
  customer_id: number;
  name: string;
}

interface InvoiceOrganization {
  company_name: string;
}

interface LineItem {
  name: string;
  start_date: string;
  end_date: string;
  quantity: number;
  sutotal: string;
  billing_type: string;
  plan_version_id: string;
  metadata: any;
}

export interface MarkInvoiceStatusAsPaid {
  invoice_id: string;
  payment_status: "paid" | "unpaid" | "voided";
}
