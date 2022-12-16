import { PricingUnit } from "./pricing-unit-type";

export interface CreateOrgAccountType {
  username: string;
  password: string;
  email: string;
  company_name: string;
  industry: string;
  invite_token?: string | null;
}

export interface UserType {
  username: string;
  email: string;
  role: string;
  status: string;
}

export interface OrganizationType {
  company_name: string;
  payment_plan: string;
  payment_provider_ids: object;
  users: UserType[];
  default_currency: PricingUnit;
  available_currencies: PricingUnit[];
  organization_id: string;
}

export interface ActionUserType extends UserType {
  string_repr: string;
}

export interface Action {
  id: number;
  actor: ActionUserType;
  verb: any;
  action_object: any;
  target: any;
  public: boolean;
  description: string;
  timestamp: string;
}

export interface PaginatedActionsType {
  next: string;
  previous: string;
  results: Action[];
}
