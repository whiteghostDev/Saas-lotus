import React, { FC, useState } from "react";
import { Card, Button } from "antd";
import {
  useQuery,
  UseQueryResult,
  useMutation,
  useQueryClient,
} from "react-query";
import { toast } from "react-toastify";
import MetricTable from "../components/Metrics/MetricTable";
import { Metrics } from "../api/api";
import {
  CategoricalFilterType,
  CreateMetricType,
  MetricType,
  NumericFilterType,
} from "../types/metric-type";
import LoadingSpinner from "../components/LoadingSpinner";
import CreateMetricForm from "../components/Metrics/CreateMetricForm";
import EventPreview from "../components/EventPreview";
import "./ViewMetrics.css";
import { PageLayout } from "../components/base/PageLayout";

const defaultMetricState: CreateMetricType = {
  event_name: "",
  usage_aggregation_type: "",
  property_name: "",
  metric_type: "counter",
  metric_name: "",
  numeric_filters: [],
  categorical_filters: [],
  is_cost_metric: false,
};

const ViewMetrics: FC = () => {
  const [visible, setVisible] = useState<boolean>(false);
  const [metricState, setMetricState] =
    useState<CreateMetricType>(defaultMetricState);

  const queryClient = useQueryClient();

  const { data, isLoading, isError }: UseQueryResult<MetricType[]> = useQuery<
    MetricType[]
  >(["metric_list"], () => Metrics.getMetrics().then((res) => res));

  const mutation = useMutation(
    (post: CreateMetricType) => Metrics.createMetric(post),
    {
      onSuccess: () => {
        setVisible(false);
        queryClient.invalidateQueries(["metric_list"]);
        toast.success("Successfully created metric", {
          position: toast.POSITION.TOP_CENTER,
        });
      },

      onMutate: () => {
        toast.loading("Creating metric...", {
          position: toast.POSITION.TOP_CENTER,
          autoClose: false,
        });
      },

      onSettled: () => {
        toast.dismiss();
      },

      onError: (error: any) => {
        toast.error(`Error creating metric: ${error.response.data.detail}`, {
          position: toast.POSITION.TOP_CENTER,
        });
      },
    }
  );
  const createMetricButton = () => {
    setMetricState(defaultMetricState);
    setVisible(true);
  };

  const onCancel = () => {
    setVisible(false);
  };

  const onSave = (metricInstance: CreateMetricType) => {
    mutation.mutate(metricInstance);
  };

  return (
    <PageLayout
      title="Metrics"
      extra={[
        <Button
          type="primary"
          size="large"
          id="create-metric-button"
          key={"create-plan"}
          onClick={createMetricButton}
        >
          Create Metric
        </Button>,
      ]}
    >
      <div className="flex flex-col space-y-4 bg-background">
        {isLoading || data === undefined ? (
          <div className="flex align-center justify-center min-h-[100px] bg-white">
            <LoadingSpinner />{" "}
          </div>
        ) : (
          <MetricTable metricArray={data} />
        )}
        {isError && <div className=" text-danger">Something went wrong</div>}
        <Card className="flex flex-row justify-center h-full">
          <EventPreview />
        </Card>
        <CreateMetricForm
          state={metricState}
          visible={visible}
          onSave={onSave}
          onCancel={onCancel}
        />
      </div>
    </PageLayout>
  );
};

export default ViewMetrics;
