import axios, { AxiosResponse } from "axios";
import { CustomerType } from "../types/customer-type";
import { PlanType } from "../types/plan-type";
import { StripeConnectType, StripeStatusType } from "../types/stripe-type";
import Cookies from "universal-cookie";

const cookies = new Cookies();

axios.defaults.headers.common["X-CSRFToken"] = cookies.get("csrftoken");

const instance = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  timeout: 15000,
  withCredentials: true,
});

const responseBody = (response: AxiosResponse) => response.data;

const requests = {
  get: (url: string) => instance.get(url).then(responseBody),
  post: (url: string, body: {}, headers?: {}) =>
    instance.post(url, body, headers).then(responseBody),
  put: (url: string, body: {}) => instance.put(url, body).then(responseBody),
  delete: (url: string) => instance.delete(url).then(responseBody),
};

export const Customer = {
  getCustomers: (): Promise<CustomerType[]> => requests.get("api/customers"),
  getACustomer: (id: number): Promise<CustomerType> =>
    requests.get(`posts/${id}`),
  createCustomer: (post: CustomerType): Promise<CustomerType> =>
    requests.post("posts", post),
};

export const Plan = {
  getCustomers: (): Promise<CustomerType[]> => requests.get("api/customers"),
  getACustomer: (id: number): Promise<CustomerType> =>
    requests.get(`posts/${id}`),
  createCustomer: (post: CustomerType): Promise<CustomerType> =>
    requests.post("posts", post),
};

export const StripeConnect = {
  getStripeConnectionStatus: (): Promise<StripeStatusType[]> =>
    requests.get("api/stripe"),
  connectStripe: (): Promise<StripeConnectType[]> =>
    requests.post("api/stripe", {}),
};

export const Authentication = {
  getSession: (): Promise<{ isAuthenticated: boolean }> =>
    requests.get("api/session/"),
  login: (
    username: string,
    password: string
  ): Promise<{ username: string; password: string }> =>
    requests.post("api/login/", { username, password }),
};
