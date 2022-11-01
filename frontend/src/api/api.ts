import axios, { AxiosResponse } from "axios";
import {
  CustomerPlus,
  CustomerType,
  CustomerTotal,
  CustomerDetailType,
} from "../types/customer-type";
import {
  PlanType,
  CreatePlanType,
  UpdatePlanType,
  PlansByCustomerArray,
  CreatePlanVersionType,
  PlanDetailType,
  PlanVersionType,
  ReplaceLaterType,
  ReplaceImmediatelyType,
  ArchivePlanVersionType,
  PlanVersionUpdateDescriptionType,
} from "../types/plan-type";
import { RevenueType } from "../types/revenue-type";
import {
  SubscriptionTotals,
  CreateSubscriptionType,
  UpdateSubscriptionType,
  SubscriptionType,
  CancelSubscriptionType,
  ChangeSubscriptionPlanType,
  TurnSubscriptionAutoRenewOffType,
} from "../types/subscription-type";
import { MetricUsage, MetricType, MetricNameType } from "../types/metric-type";
import { EventPages } from "../types/event-type";
import { CreateOrgAccountType } from "../types/account-type";
import { cancelSubscriptionType } from "../components/Customers/CustomerSubscriptionView";
import { FeatureType } from "../types/feature-type";
import Cookies from "universal-cookie";
import {
  CreateBacktestType,
  BacktestType,
  BacktestResultType,
} from "../types/experiment-type";
import { version } from "react";

const cookies = new Cookies();

const API_HOST = import.meta.env.VITE_API_URL;

axios.defaults.headers.common["Authorization"] = `Token ${cookies.get(
  "Token"
)}`;

axios.defaults.baseURL = API_HOST;
// axios.defaults.xsrfCookieName = "csrftoken";
// axios.defaults.xsrfHeaderName = "X-CSRFToken";

export const instance = axios.create({
  timeout: 15000,
  withCredentials: true,
});

const responseBody = (response: AxiosResponse) => response.data;

const requests = {
  get: (url: string, params?: {}) =>
    instance.get(url, params).then(responseBody),
  post: (url: string, body: {}, headers?: {}) =>
    instance.post(url, body, headers).then(responseBody),
  patch: (url: string, body: {}) =>
    instance.patch(url, body).then(responseBody),
  delete: (url: string, params?: {}) => instance.delete(url).then(responseBody),
};

export const Customer = {
  getCustomers: (): Promise<CustomerPlus[]> =>
    requests.get("api/customer_summary/"),
  getACustomer: (customer_id: string): Promise<CustomerType> =>
    requests.get(`api/customers/${customer_id}`),
  createCustomer: (post: CustomerType): Promise<CustomerType> =>
    requests.post("api/customers/", post),
  getCustomerTotals: (): Promise<CustomerTotal[]> =>
    requests.get("api/customer_totals/"),
  getCustomerDetail: (customer_id: string): Promise<CustomerDetailType> =>
    requests.get(`api/customer_detail/`, { params: { customer_id } }),
  //Subscription handling
  createSubscription: (
    post: CreateSubscriptionType
  ): Promise<SubscriptionType> => requests.post("api/subscriptions/", post),
  updateSubscription: (
    //this is the general version, try to use the specific ones below
    subscription_id: string,
    post: UpdateSubscriptionType
  ): Promise<UpdateSubscriptionType> =>
    requests.patch(`api/subscriptions/${subscription_id}/`, post),
  cancelSubscription: (
    subscription_id: string,
    post: CancelSubscriptionType
  ): Promise<CancelSubscriptionType> =>
    requests.patch(`api/subscriptions/${subscription_id}/`, post),
  changeSubscriptionPlan: (
    subscription_id: string,
    post: ChangeSubscriptionPlanType
  ): Promise<ChangeSubscriptionPlanType> =>
    requests.patch(`api/subscriptions/${subscription_id}/`, post),
  turnSubscriptionAutoRenewOff: (
    subscription_id: string,
    post: TurnSubscriptionAutoRenewOffType
  ): Promise<TurnSubscriptionAutoRenewOffType> =>
    requests.patch(`api/subscriptions/${subscription_id}/`, post),
};

export const Plan = {
  //get methods
  getPlans: (): Promise<PlanType[]> => requests.get("api/plans/"),
  getPlan: (plan_id: string): Promise<PlanDetailType> =>
    requests.get(`api/plans/${plan_id}/`),
  //create plan
  createPlan: (post: CreatePlanType): Promise<PlanType> =>
    requests.post("api/plans/", post),
  //create plan version
  createVersion: (post: CreatePlanVersionType): Promise<PlanVersionType> =>
    requests.post("api/plan_versions/", post),
  //update plans methods
  updatePlan: (
    plan_id: string,
    post: UpdatePlanType
  ): Promise<UpdatePlanType> => requests.patch(`api/plans/${plan_id}/`, post),
  //update plan versions methods
  updatePlanVersionDescription: (
    version_id: string,
    post: PlanVersionUpdateDescriptionType
  ): Promise<PlanVersionUpdateDescriptionType> =>
    requests.patch(`api/plan_versions/${version_id}/`, post),
  replacePlanVersionLater: (
    version_id: string,
    post: ReplaceLaterType
  ): Promise<ReplaceLaterType> =>
    requests.patch(`api/plan_versions/${version_id}/`, post),
  replacePlanVersionImmediately: (
    version_id: string,
    post: ReplaceImmediatelyType
  ): Promise<ReplaceImmediatelyType> =>
    requests.patch(`api/plan_versions/${version_id}/`, post),
  archivePlanVersion: (
    version_id: string,
    post: ArchivePlanVersionType
  ): Promise<ArchivePlanVersionType> =>
    requests.patch(`api/plan_versions/${version_id}/`, post),
};

export const Alerts = {
  getUrls: (): Promise<any> => requests.get("api/webhooks/"),
  addUrl: (url: string): Promise<any> =>
    requests.post("api/webhooks/", { webhook_url: url }),
  deleteUrl: (id: number): Promise<any> =>
    requests.delete(`api/webhooks/${id}`),
};

export const Authentication = {
  getSession: (): Promise<{ isAuthenticated: boolean }> =>
    requests.get("api/session/"),
  login: (
    username: string,
    password: string
  ): Promise<{ detail: any; token: string }> =>
    requests.post("api/login/", { username, password }),
  logout: (): Promise<{}> => requests.post("api/logout/", {}),
  registerCreate: (
    register: CreateOrgAccountType
  ): Promise<{ username: string; password: string }> =>
    requests.post("api/register/", {
      register,
    }),
  resetPassword: (email: string): Promise<{ email: string }> =>
    requests.post("api/user/password/reset/init/", { email }),
  setNewPassword: (
    token: string,
    userId: string,
    password: string
  ): Promise<{ detail: any; token: string }> =>
    requests.post("api/user/password/reset/", { token, userId, password }),
};

export const Organization = {
  invite: (email): Promise<{ email: string }> =>
    requests.post("api/organization/invite", { email }),
  get: (): Promise<any> => requests.get("api/organization"),
};

export const GetRevenue = {
  getMonthlyRevenue: (
    period_1_start_date: string,
    period_1_end_date: string,
    period_2_start_date: string,
    period_2_end_date: string
  ): Promise<RevenueType> =>
    requests.get("api/period_metric_revenue/", {
      params: {
        period_1_start_date,
        period_1_end_date,
        period_2_start_date,
        period_2_end_date,
      },
    }),
};

export const GetSubscriptions = {
  getSubscriptionOverview: (
    period_1_start_date: string,
    period_1_end_date: string,
    period_2_start_date: string,
    period_2_end_date: string
  ): Promise<SubscriptionTotals> =>
    requests.get("api/period_subscriptions/", {
      params: {
        period_1_start_date,
        period_1_end_date,
        period_2_start_date,
        period_2_end_date,
      },
    }),
};

export const PlansByCustomer = {
  getPlansByCustomer: (): Promise<PlansByCustomerArray> =>
    requests.get("api/plans_by_customer/"),
};

export const Features = {
  getFeatures: (): Promise<FeatureType[]> => requests.get("api/features/"),
  createFeature: (post: FeatureType): Promise<FeatureType> =>
    requests.post("api/features/", post),
};

export const Metrics = {
  getMetricUsage: (
    start_date: string,
    end_date: string,
    top_n_customers?: number
  ): Promise<MetricUsage> =>
    requests.get("api/period_metric_usage/", {
      params: { start_date, end_date, top_n_customers },
    }),
  getMetrics: (): Promise<MetricType[]> => requests.get("api/metrics/"),
  createMetric: (post: MetricType): Promise<MetricType> =>
    requests.post("api/metrics/", post),
  deleteMetric: (id: number): Promise<{}> =>
    requests.delete(`api/metrics/${id}`),
};

export const Events = {
  getEventPreviews: (c: string): Promise<EventPages> =>
    requests.get("api/events/", { params: { c } }),
};

export const APIToken = {
  newAPIToken: (): Promise<{ api_key: string }> =>
    requests.get("api/new_api_key/", {}),
};

export const Backtests = {
  getBacktests: (): Promise<BacktestType[]> => requests.get("api/backtests/"),
  createBacktest: (post: CreateBacktestType): Promise<CreateBacktestType> =>
    requests.post("api/backtests/", post),
  getBacktestResults: (id: string): Promise<BacktestResultType> =>
    requests.get(`api/backtests/${id}/`),
};