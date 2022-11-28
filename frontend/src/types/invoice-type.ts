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
}

interface InvoiceCustomer {
  customer_id: number;
  name: string;
}

interface InvoiceOrganization {
  company_name: string;
}

interface LineItem {
  components: object;
  flat_amount_due: number;
  total_amount_due: number;
  usage_amount_due: number;
}

export interface MarkInvoiceStatusAsPaid {
  invoice_id: string;
  payment_status: "paid" | "unpaid" | "voided";
}
