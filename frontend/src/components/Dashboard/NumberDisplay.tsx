import React, { Fragment, useEffect, useState } from "react";
import LoadingSpinner from "../LoadingSpinner";
import { Paper } from "../base/Paper";
import ContentLoader from "react-content-loader";

const computePercentageChange = (
  current: number | undefined,
  previous: number | undefined
): number => {
  if (previous === 0 || current === undefined || previous === undefined) {
    return 0;
  }
  return ((current - previous) / previous) * 100;
};

const displayMetric = (metric: number | undefined): number => {
  if (metric === undefined) {
    return 0;
  }
  return metric;
};

const renderMetric = (metric: number | undefined, currency?: string) => {
  if (metric === undefined) {
    return 0;
  }
  if (currency) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(metric);
  }
  return metric;
};

const PlaceholderLoader = (props) => (
  <ContentLoader
    speed={2}
    width={400}
    viewBox="0 0 400 70"
    backgroundColor="#f3f3f3"
    foregroundColor="#ecebeb"
    {...props}
  >
    <rect x="16" y="8" rx="3" ry="3" width="72" height="30" />
    <rect x="16" y="48" rx="3" ry="3" width="120" height="18" />
  </ContentLoader>
);

function NumberDisplay(props: {
  metric_1: number | undefined;
  metric_2: number | undefined;
  isLoading: boolean;
  title: string;
  currency?: string;
}) {
  const [percentageChange, setPercentageChange] = useState<number>(0);

  useEffect(() => {
    setPercentageChange(
      computePercentageChange(props.metric_1, props.metric_2)
    );
  }, [props.metric_1, props.metric_2]);
  return (
    <Paper border={true}>
      <div className="grid grid-flow-col auto-cols-auto  justify-between">
        <div>
          <p className="text-sm mb-4 leading-[18px] font-normal">
            {props.title}
          </p>
          {props.isLoading ? (
            <div className="flex flex-row justify-center">
              <PlaceholderLoader />
            </div>
          ) : (
            <Fragment>
              <span className="text-3xl font-bold mb-4">
                {renderMetric(displayMetric(props.metric_1), props.currency)}
              </span>
              <p className="text-sm mb-4 mt-4 leading-[18px] font-normal">
                Prev. Period{" "}
                {percentageChange >= 0 ? (
                  <span className="text-[#34B220] ">
                    +{percentageChange.toFixed(2)}%{" "}
                  </span>
                ) : (
                  <span className="text-[#cf1322] ">
                    {percentageChange.toFixed(0)}%{" "}
                  </span>
                )}
              </p>
            </Fragment>
          )}
        </div>
      </div>
    </Paper>
  );
}

export default NumberDisplay;
