import React, { FC } from "react";
import { Button } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useQuery, UseQueryResult } from "react-query";
import { Addon } from "../api/api";
import DBSVG from "../components/base/db-svg";
import { PageLayout } from "../components/base/PageLayout";
import LoadingSpinner from "../components/LoadingSpinner";
import AddOnsCard from "../components/Addons/AddonsCard/AddOnCard";
import { AddonType } from "../types/addon-type";

const ViewAddOns: FC = () => {
  const navigate = useNavigate();

  const { data: addOns, isLoading }: UseQueryResult<AddonType[]> = useQuery<
    AddonType[]
  >(
    ["add-ons"],
    () =>
      Addon.getAddons().then((res) => res),
    {
      refetchOnMount: "always",
    }
  );

  const navigateCreatePlan = () => {
    navigate("/create-addons");
  };

  return (
    <PageLayout
      title="Add-ons"
      className="text-[24px] font-alliance"
      extra={
        addOns?.length && !isLoading
          ? [
              <Button
                onClick={navigateCreatePlan}
                type="primary"
                size="large"
                key="create-plan"
                className="hover:!bg-primary-700"
                style={{ background: "#C3986B", borderColor: "#C3986B" }}
              >
                <div className="flex items-center  justify-between text-white">
                  <div>
                    <PlusOutlined className="!text-white w-12 h-12 cursor-pointer" />
                    Create Add-on
                  </div>
                </div>
              </Button>,
            ]
          : []
      }
    >
      <div className="flex flex-col">
        {addOns?.length ? (
          <div className="grid gap-20  grid-cols-1 md:grid-cols-2 xl:grid-cols-4">
            {addOns?.map((item, key) => (
              <AddOnsCard add_on={item} key={key} />
            ))}
          </div>
        ) : (
          <div>
            {/* <div className="mt-[40%]" /> */}
            {isLoading ? (
              <div className="flex items-center justify-center">
                <div className="mt-[40%]" />
                <LoadingSpinner />
              </div>
            ) : (
              <div className="flex flex-col items-center p-4 justify-center bg-card">
                <DBSVG />
                <div className="text-lg mt-2 mb-2 font-alliance">
                  No add-ons created yet!
                </div>
                <div className="text-base Inter mt-2 mb-2">
                  You didn&apos;t create an add-on yet, you can start by
                  creating one. You can attach add-ons to customers and plans.
                </div>
                <Button
                  onClick={navigateCreatePlan}
                  type="primary"
                  size="large"
                  key="create-plan"
                  className="hover:!bg-primary-700"
                  style={{ background: "#C3986B", borderColor: "#C3986B" }}
                >
                  <div className="flex items-center  justify-between text-white">
                    <div>
                      <PlusOutlined className="!text-white w-12 h-12 cursor-pointer" />
                      Create
                    </div>
                  </div>
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </PageLayout>
  );
};

export default ViewAddOns;
