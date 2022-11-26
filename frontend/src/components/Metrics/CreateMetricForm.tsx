import { Modal, Form, Input, Select, Radio, Tooltip, Switch } from "antd";
import { MetricType } from "../../types/metric-type";
import React, { Fragment, useEffect, useState } from "react";
const { Option } = Select;

export interface CreateMetricState extends MetricType {
  title: string;
  usage_aggregation_type_2: string;
  property_name_2: string;
  granularity_2?: string;
}

const CreateMetricForm = (props: {
  state: CreateMetricState;
  visible: boolean;
  onSave: (state: CreateMetricState) => void;
  onCancel: () => void;
}) => {
  const [form] = Form.useForm();
  const [eventType, setEventType] = useState("counter");
  const [rate, setRate] = useState(false);
  const [preset, setPreset] = useState("none");
  const [costMetric, setCostMetric] = useState(false);

  const changeFormPreset = (preset: string) => {
    switch (preset) {
      case "none":
        setEventType("counter");
        setRate(false);

        form.resetFields();
        break;
      case "seats":
        setEventType("stateful");
        setRate(false);
        setCostMetric(false);

        form.setFieldsValue({
          aggregation_type_2: "max",
          event_name: "seats",
          metric_type: "stateful",
          property_name_2: "seat_count",
          granularity_2: "days",
          billable_metric_name: "Seats",
          event_type: "total",
        });
        break;
      case "calls":
        setEventType("counter");
        setRate(false);
        setCostMetric(false);

        form.setFieldsValue({
          usage_aggregation_type: "count",
          billable_metric_name: "API Post Calls",
          event_name: "api_post",
          metric_type: "counter",
        });
        break;
      case "rate":
        setEventType("counter");
        setRate(true);
        setCostMetric(false);

        form.setFieldsValue({
          usage_aggregation_type: "sum",
          billable_metric_name: "Database Insert Rate",
          event_name: "db_insert",
          metric_type: "counter",
          property_name: "#_of_inserts",
          rate: true,
          billable_aggregation_type: "max",
          granularity: "minutes",
        });
    }
  };

  return (
    <Modal
      visible={props.visible}
      title={props.state.title}
      okText="Create"
      okType="default"
      cancelText="Cancel"
      width={800}
      onCancel={props.onCancel}
      onOk={() => {
        form
          .validateFields()
          .then((values) => {
            values.is_cost_metric = costMetric;
            if (rate) {
              values.metric_type = "rate";
            }
            props.onSave(values);
            form.resetFields();
            setRate(false);
            setEventType("counter");
            setPreset("none");
          })
          .catch((info) => {});
      }}
    >
      <div className="grid grid-cols-8 my-4 gap-4 items-center">
        <h3 className="col-span-2">Templates</h3>
        <Radio.Group
          buttonStyle="solid"
          optionType="button"
          className="col-span-6 space-x-4"
          value={preset}
          onChange={(e) => {
            setPreset(e.target.value);
            changeFormPreset(e.target.value);
          }}
        >
          <Radio value="none">No Template</Radio>
          <Radio value="seats">Seats (prorated per day)</Radio>
          <Radio value="calls">API Calls</Radio>
          <Radio value="rate">Insert Rate</Radio>
        </Radio.Group>
      </div>
      <div className="seperator" />
      <Form
        form={form}
        layout="vertical"
        name="customer_form"
        initialValues={{
          metric_type: "counter",
          usage_aggregation_type: "count",
          usage_aggregation_type_2: "max",
          granularity_2: "days",
          event_type: "total",
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          <Tooltip
            placement="left"
            title="Define a display name for this metric"
          >
            <Form.Item
              name="billable_metric_name"
              label="Metric Name"
              rules={[
                {
                  required: true,
                  message: "Please define a unique name for this metric",
                },
              ]}
            >
              <Input />
            </Form.Item>
          </Tooltip>
          <Form.Item
            name="event_name"
            label="Event Name"
            rules={[
              {
                required: true,
                message: "Please input the name of the event you want to track",
              },
            ]}
          >
            <Input />
          </Form.Item>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Form.Item
            name="metric_type"
            className="justify-center"
            label="Type"
            rules={[
              {
                required: true,
                message: "Metric type is required",
              },
            ]}
          >
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              value={eventType}
              defaultValue={eventType}
              onChange={(e) => {
                setEventType(e.target.value);
                if (e.target.value === "counter") {
                  setRate(false);
                }
              }}
            >
              <Radio value="counter">Counter</Radio>
              <Radio value="stateful">Continuous</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="Does this metric represent a cost?">
            <Switch
              checked={costMetric}
              onChange={() => {
                setCostMetric(!costMetric);
                if (!costMetric) {
                  form.setFieldsValue({
                    is_cost_metric: false,
                  });
                } else {
                  form.setFieldsValue({
                    is_cost_metric: true,
                  });
                }
              }}
            />
          </Form.Item>
        </div>
        <Form.Item
          noStyle
          shouldUpdate={(prevValues, currentValues) =>
            prevValues.metric_type !== currentValues.metric_type
          }
        >
          {eventType === "counter" && (
            <Fragment>
              <Form.Item
                name="usage_aggregation_type"
                label="Aggregation Type"
                rules={[
                  {
                    required: true,
                    message: "Aggregation type is required",
                  },
                  //if rate is selected, don't allow unique
                  {
                    validator: (_, value) => {
                      if (rate && value === "unique") {
                        return Promise.reject(
                          new Error("Cannot use unique with rate")
                        );
                      }
                      return Promise.resolve();
                    },
                  },
                ]}
              >
                <Select defaultValue={"count"}>
                  <Option value="count">count</Option>
                  <Option value="unique">unique</Option>
                  <Option value="sum">sum</Option>
                  <Option value="max">max</Option>
                </Select>
              </Form.Item>
              <Form.Item
                noStyle
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues.usage_aggregation_type !==
                    currentValues.usage_aggregation_type ||
                  prevValues.metric_type !== currentValues.metric_type
                }
              >
                {({ getFieldValue }) =>
                  getFieldValue("usage_aggregation_type") === "sum" ||
                  getFieldValue("usage_aggregation_type") === "max" ||
                  getFieldValue("usage_aggregation_type") === "unique" ? (
                    <Form.Item
                      name="property_name"
                      label="Property Name"
                      rules={[{ required: true }]}
                    >
                      <Input />
                    </Form.Item>
                  ) : null
                }
              </Form.Item>
              <div className="mb-5">
                <h4>
                  Add Rate. This will allow you to track the metric over windows
                  of time.
                </h4>
                <Switch
                  checked={rate}
                  onChange={() => {
                    setRate(!rate);
                    if (!rate) {
                      form.setFieldsValue({
                        billable_aggregation_type: "max",
                        granularity: "days",
                      });
                    } else {
                      form.setFieldsValue({
                        metric_type: "counter",
                      });
                    }
                  }}
                  // disabled={
                  //   form.getFieldValue("usage_aggregation_type") !== "unique"
                  // }
                />
              </div>

              {rate && (
                <Fragment>
                  <Form.Item
                    name="granularity"
                    label="Rate Period"
                    rules={[
                      {
                        required: true,
                        message: "Period is required",
                      },
                    ]}
                  >
                    <Select defaultValue="days">
                      <Option value="days">day</Option>
                      <Option value="hours">hour</Option>
                      <Option value="minutes">minute</Option>
                    </Select>
                  </Form.Item>
                  <Form.Item
                    name="billable_aggregation_type"
                    label="Rate Aggregation Type"
                    rules={[
                      {
                        required: true,
                        message: "Aggregation type is required",
                      },
                    ]}
                  >
                    <Select defaultValue={"max"}>
                      <Option value="max">max</Option>
                    </Select>
                  </Form.Item>
                </Fragment>
              )}
            </Fragment>
          )}
          {eventType === "stateful" && (
            <Fragment>
              <div className="grid grid-cols-2 gap-4">
                <Form.Item
                  name="usage_aggregation_type_2"
                  label="Aggregation Type"
                  rules={[
                    {
                      required: true,
                      message: "Aggregation type is required",
                    },
                  ]}
                >
                  <Select defaultValue={"max"}>
                    <Option value="max">max</Option>
                    <Option value="latest">latest</Option>
                  </Select>
                </Form.Item>
                <Form.Item
                  name="event_type"
                  label="Event Type (how the property amount is reported)"
                  rules={[{ required: true }]}
                >
                  <Select defaultValue={"total"}>
                    <Option value="total">total</Option>
                    <Option value="delta">delta</Option>
                  </Select>
                </Form.Item>
              </div>

              <Form.Item
                name="property_name_2"
                label="Property Name"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
              <Form.Item
                name="granularity_2"
                label="Period"
                rules={[
                  {
                    required: true,
                    message: "Period is required",
                  },
                ]}
              >
                <Select defaultValue={"days"}>
                  <Option value="days">day</Option>
                  <Option value="hours">hour</Option>
                  <Option value="weeks">week</Option>
                </Select>
              </Form.Item>
            </Fragment>
          )}
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default CreateMetricForm;
