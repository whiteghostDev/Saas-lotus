// @ts-ignore
import React, { useState } from "react";
import { Form, Tabs, Modal, Select } from "antd";
import { PlanType } from "../../types/plan-type";
import {
  CreateSubscriptionType,
  TurnSubscriptionAutoRenewOffType,
  ChangeSubscriptionPlanType,
  CancelSubscriptionType,
} from "../../types/subscription-type";
import LoadingSpinner from "../LoadingSpinner";
import { Customer } from "../../api/api";
import SubscriptionView from "./CustomerSubscriptionView";
import {
  useMutation,
  useQueryClient,
  useQuery,
  UseQueryResult,
} from "react-query";
import {
  CustomerDetailType,
  CustomerDetailSubscription,
} from "../../types/customer-type";
import "./CustomerDetail.css";
import CustomerInvoiceView from "./CustomerInvoices";
import CustomerBalancedAdjustments from "./CustomerBalancedAdjustments";

const { Option } = Select;

function CustomerDetail(props: {
  visible: boolean;
  onCancel: () => void;
  customer_id: string;
  plans: PlanType[] | undefined;
  changePlan: (plan_id: string, customer_id: string) => void;
}) {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();

  const [customerSubscriptions, setCustomerSubscriptions] = useState<
    CustomerDetailSubscription[]
  >([]);

  const { data, isLoading }: UseQueryResult<CustomerDetailType> =
    useQuery<CustomerDetailType>(
      ["customer_detail", props.customer_id],
      () =>
        Customer.getCustomerDetail(props.customer_id).then((res) => {
          setCustomerSubscriptions(res.subscriptions);
          return res;
        }),
      {
        enabled: props.visible,
      }
    );

  const createSubscriptionMutation = useMutation(
    (post: CreateSubscriptionType) => Customer.createSubscription(post),
    {
      onSettled: () => {
        queryClient.invalidateQueries(["customer_list"]);
        queryClient.invalidateQueries(["customer_detail", props.customer_id]);
      },
    }
  );

  const cancelSubscriptionMutation = useMutation(
    (obj: { subscription_id: string; post: CancelSubscriptionType }) =>
      Customer.cancelSubscription(obj.subscription_id, obj.post),
    {
      onSettled: () => {
        queryClient.invalidateQueries(["customer_list"]);
        queryClient.invalidateQueries(["customer_detail", props.customer_id]);
      },
    }
  );

  const changeSubscriptionPlanMutation = useMutation(
    (obj: { subscription_id: string; post: ChangeSubscriptionPlanType }) =>
      Customer.changeSubscriptionPlan(obj.subscription_id, obj.post),
    {
      onSettled: () => {
        queryClient.invalidateQueries(["customer_list"]);
        queryClient.invalidateQueries(["customer_detail", props.customer_id]);
      },
    }
  );

  const turnSubscriptionAutoRenewOffMutation = useMutation(
    (obj: {
      subscription_id: string;
      post: TurnSubscriptionAutoRenewOffType;
    }) => Customer.turnSubscriptionAutoRenewOff(obj.subscription_id, obj.post),
    {
      onSettled: () => {
        queryClient.invalidateQueries(["customer_list"]);
        queryClient.invalidateQueries(["customer_detail", props.customer_id]);
      },
    }
  );

  const cancelSubscription = (
    subscription_id: string,
    props: CancelSubscriptionType
  ) => {
    cancelSubscriptionMutation.mutate({
      subscription_id: subscription_id,
      post: props,
    });
  };

  const changeSubscriptionPlan = (
    subscription_id: string,
    props: ChangeSubscriptionPlanType
  ) => {
    changeSubscriptionPlanMutation.mutate({
      subscription_id: subscription_id,
      post: props,
    });
  };

  const turnSubscriptionAutoRenewOff = (
    subscription_id: string,
    props: TurnSubscriptionAutoRenewOffType
  ) => {
    turnSubscriptionAutoRenewOffMutation.mutate({
      subscription_id: subscription_id,
      post: props,
    });
  };

  const createSubscription = (props: CreateSubscriptionType) => {
    createSubscriptionMutation.mutate(props);
  };

  return (
    <Modal
      visible={props.visible}
      title={"Customer Detail"}
      onCancel={props.onCancel}
      okType="default"
      onOk={props.onCancel}
      footer={null}
      width={1000}
    >
      {props.plans === undefined ? (
        <div>
          <LoadingSpinner />
        </div>
      ) : (
        <div className="flex justify-between flex-col max-w mx-3">
          <div className="text-left	">
            <h1 className="mb-3">{data?.customer_name}</h1>
            <div className="flex flex-row">
              <div className="plansDetailLabel">ID:&nbsp; </div>
              <div className="plansDetailValue">{props.customer_id}</div>
            </div>
          </div>
          <div
            className="flex items-center flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <Tabs defaultActiveKey="subscriptions" centered className="w-full">
              <Tabs.TabPane tab="Detail" key="detail">
                {data !== undefined ? (
                  <div className="grid grid-cols-2">
                    <div className=" space-y-3">
                      <h2 className="mb-2">Info</h2>
                      <p>Email: {data.email}</p>
                      <p>Billing Address: {data.billing_address}</p>
                    </div>
                    <div className="space-y-3">{/* <h2>Timeline</h2> */}</div>
                  </div>
                ) : (
                  <h2> No Data </h2>
                )}
              </Tabs.TabPane>
              <Tabs.TabPane tab="Subscriptions" key="subscriptions">
                {data !== undefined ? (
                  <div key={props.customer_id}>
                    <SubscriptionView
                      customer_id={props.customer_id}
                      subscriptions={data?.subscriptions}
                      plans={props.plans}
                      onCreate={createSubscription}
                      onCancel={cancelSubscription}
                      onPlanChange={changeSubscriptionPlan}
                      onAutoRenewOff={turnSubscriptionAutoRenewOff}
                    />
                  </div>
                ) : null}
              </Tabs.TabPane>
              <Tabs.TabPane tab="Invoices" key="invoices">
                <CustomerInvoiceView invoices={data?.invoices} />
              </Tabs.TabPane>
              <Tabs.TabPane tab="Credits" key="credits">
                    <CustomerBalancedAdjustments balanceAdjustments={data?.balance_adjustments} />
                </Tabs.TabPane>{" "}
            </Tabs>
          </div>
        </div>
      )}
    </Modal>
  );
}

export default CustomerDetail;
