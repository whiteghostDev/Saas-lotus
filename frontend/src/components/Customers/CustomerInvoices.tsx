/* eslint-disable camelcase */
/* eslint-disable prefer-template */
/* eslint-disable no-nested-ternary */
import { Button, Dropdown, Menu, Table, Tag, Tooltip } from "antd";
import React, { FC, useEffect } from "react";
import dayjs from "dayjs";
import { useMutation, useQuery } from '@tanstack/react-query';
import { toast } from "react-toastify";
import { MoreOutlined } from "@ant-design/icons";
import axios from "axios";
import { ProTable } from "@ant-design/pro-components";
import type { ProColumns } from "@ant-design/pro-components";
import { integrationsMap } from "../../types/payment-processor-type";
import { Invoices } from "../../api/api";
import { InvoiceType, MarkPaymentStatusAsPaid } from "../../types/invoice-type";
import { components } from "../../gen-types";

const downloadFile = async (s3link) => {
  if (!s3link) {
    toast.error("No file to download");
    return;
  }
  window.open(s3link);
};

const getPdfUrl = async (
  invoice: components["schemas"]["CustomerDetail"]["invoices"][0]
) => {
  try {
    const response = await Invoices.getInvoiceUrl(invoice.invoice_id);
    const pdfUrl = response.url;
    downloadFile(pdfUrl);
  } catch (err) {
    toast.error("Error downloading file");
  }
};

const lotusUrl = new URL("./lotusIcon.svg", import.meta.url).href;

interface Props {
  invoices: components["schemas"]["CustomerDetail"]["invoices"] | undefined;
  paymentMethod: string;
}

const CustomerInvoiceView: FC<Props> = ({ invoices, paymentMethod }) => {
  const [selectedRecord, setSelectedRecord] =
    React.useState<components["schemas"]["CustomerDetail"]["invoices"][0]>();
  const changeStatus = useMutation(
    (post: MarkPaymentStatusAsPaid) => Invoices.changeStatus(post),
    {
      onSuccess: (data) => {
        const status = data.payment_status.toUpperCase();
        toast.success(`Successfully Changed Invoice Status to ${status}`, {
          position: toast.POSITION.TOP_CENTER,
        });
        selectedRecord.payment_status = data.payment_status;
      },
      onError: () => {
        toast.error("Failed to Changed Invoice Status", {
          position: toast.POSITION.TOP_CENTER,
        });
      },
    }
  );

  const sendToPaymentProcessor = useMutation(
    (invoice_id: string) => Invoices.sendToPaymentProcessor(invoice_id),
    {
      onSuccess: (data) => {
        toast.success("Successfully sent to payment processor", {
          position: toast.POSITION.TOP_CENTER,
        });
        selectedRecord.external_payment_obj_type =
          data.external_payment_obj_type;
      },
      onError: () => {
        toast.error("Failed to send to payment processor", {
          position: toast.POSITION.TOP_CENTER,
        });
      },
    }
  );

  useEffect(() => {
    if (selectedRecord !== undefined) {
      changeStatus.mutate({
        invoice_id: selectedRecord.invoice_id,
        payment_status:
          selectedRecord.payment_status === "unpaid" ? "paid" : "unpaid",
      });
    }
  }, [selectedRecord]);

  const columns: ProColumns<
    components["schemas"]["CustomerDetail"]["invoices"][0]
  >[] = [
    {
      title: "Connections",
      dataIndex: "connections",
      width: 100,
      key: "connections",
      render: (_, record) => (
        <div className="flex gap-1">
          {record.external_payment_obj_type && (
            <Tooltip title={record.external_payment_obj_id}>
              {record.external_payment_obj_url ? (
                <a
                  href={record.external_payment_obj_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <img
                    className="sourceIcon"
                    src={
                      record.external_payment_obj_type === "stripe"
                        ? integrationsMap.stripe.icon
                        : record.external_payment_obj_type === "braintree"
                        ? integrationsMap.braintree.icon
                        : lotusUrl
                    }
                    alt={`${record.external_payment_obj_type} icon`}
                  />
                </a>
              ) : (
                <img
                  className="sourceIcon"
                  src={
                    record.external_payment_obj_type === "stripe"
                      ? integrationsMap.stripe.icon
                      : integrationsMap.braintree.icon
                  }
                  alt={`${record.external_payment_obj_type} icon`}
                />
              )}
            </Tooltip>
          )}
          {record.crm_provider && (
            <Tooltip title={record.crm_provider_id}>
              {record.crm_provider_url ? (
                <a
                  href={record.crm_provider_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <img
                    className="sourceIcon"
                    src={integrationsMap.salesforce.icon}
                    alt={`${record.crm_provider} icon`}
                  />
                </a>
              ) : (
                <img
                  className="sourceIcon"
                  src={
                    record.crm_provider === "salesforce"
                      ? integrationsMap.salesforce.icon
                      : lotusUrl
                  }
                  alt={`${record.crm_provider} icon`}
                />
              )}
            </Tooltip>
          )}
        </div>
      ),
    },
    {
      title: "Invoice #",
      dataIndex: "invoice_number",
      key: "invoice_number",
    },
    {
      title: "Amount",
      dataIndex: "cost_due",
      key: "cost_due",
      render: (_, { cost_due }) => (
        <span>${parseFloat(String(cost_due)).toFixed(2)}</span>
      ),
    },
    {
      title: "Issue Date",
      dataIndex: "issue_date",
      key: "issue_date",
      render: (_, { issue_date }) => (
        <span>{dayjs(issue_date).format("YYYY/MM/DD")}</span>
      ),
    },
    {
      title: "Status",
      dataIndex: "payment_status",
      key: "status",
      render: (
        _,
        record: components["schemas"]["CustomerDetail"]["invoices"][0]
      ) => (
        <div className="flex">
          {record.external_payment_obj_type ? (
            record.external_payment_obj_url ? (
              <Tooltip
                title={
                  "Source: " +
                  (record.external_payment_obj_type === "stripe"
                    ? "Stripe"
                    : "Braintree")
                }
              >
                <a
                  href={record.external_payment_obj_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Tag
                    color="grey"
                    key={
                      record.external_payment_obj_status ||
                      record.payment_status
                    }
                  >
                    {record.external_payment_obj_status ||
                      record.payment_status}
                  </Tag>
                </a>
              </Tooltip>
            ) : (
              <Tooltip
                title={
                  "Source: " +
                  (record.external_payment_obj_type === "stripe"
                    ? "Stripe"
                    : "Braintree")
                }
              >
                <Tag
                  color="grey"
                  key={
                    record.external_payment_obj_status || record.payment_status
                  }
                >
                  {record.external_payment_obj_status || record.payment_status}
                </Tag>
              </Tooltip>
            )
          ) : (
            <Tag
              color={record.payment_status === "paid" ? "green" : "red"}
              key={record.payment_status}
            >
              {record.payment_status.toUpperCase()}
            </Tag>
          )}

          <div
            className="ml-auto"
            aria-hidden
            onClick={(e) => e.stopPropagation()}
          >
            <Dropdown
              overlay={
                <Menu>
                  <Menu.Item
                    key="1"
                    onClick={() => {
                      if ((import.meta as any).env.VITE_IS_DEMO === "true") {
                        toast.error("This feature is disabled in the demo", {
                          position: toast.POSITION.TOP_CENTER,
                        });
                      } else {
                        getPdfUrl(record);
                      }
                    }}
                  >
                    <div className="archiveLabel">Download Invoice PDF</div>
                  </Menu.Item>
                  {!record.external_payment_obj_type &&
                    record.payment_status === "unpaid" && (
                      <Menu.Item
                        key="2"
                        onClick={() => {
                          if (
                            (import.meta as any).env.VITE_IS_DEMO === "true"
                          ) {
                            toast.error(
                              "This feature is disabled in the demo",
                              {
                                position: toast.POSITION.TOP_CENTER,
                              }
                            );
                          } else {
                            if (selectedRecord === record) {
                              changeStatus.mutate({
                                invoice_id: record.invoice_id,
                                payment_status: "paid",
                              });
                            } else {
                              setSelectedRecord(record);
                            }
                          }
                        }}
                      >
                        <div className="archiveLabel">Mark As Paid</div>
                      </Menu.Item>
                    )}
                  {!record.external_payment_obj_type &&
                    paymentMethod &&
                    record.payment_status === "unpaid" && (
                      <Menu.Item
                        key="2"
                        onClick={() => {
                          if (selectedRecord === record) {
                            sendToPaymentProcessor.mutate(record.invoice_id);
                          } else {
                            setSelectedRecord(record);
                          }
                        }}
                      >
                        <div className="archiveLabel">
                          Send to Payment Processor
                        </div>
                      </Menu.Item>
                    )}
                </Menu>
              }
              trigger={["click"]}
            >
              <Button
                type="text"
                size="small"
                onClick={(e) => e.preventDefault()}
              >
                <MoreOutlined />
              </Button>
            </Dropdown>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div>
      <h2 className="mb-2 pb-4 pt-4 font-bold text-main">Invoices</h2>
      {invoices !== undefined ? (
        <ProTable
          columns={columns}
          dataSource={invoices}
          rowKey="invoice_id"
          pagination={{
            showTotal: (total, range) => (
              <div>{`${range[0]}-${range[1]} of ${total} total items`}</div>
            ),
            pageSize: 8,
          }}
          options={false}
          toolBarRender={false}
          search={false}
        />
      ) : (
        <p>No invoices found</p>
      )}
    </div>
  );
};

export default CustomerInvoiceView;
