import React from "react";
import capitalize from "../../../helpers/capitalize";
import { Typography } from "antd";
import { AddonType } from "../../../types/addon-type";
import createShortenedText from "../../../helpers/createShortenedText";
import CopyText from "../../base/CopytoClipboard";
import useMediaQuery from "../../../hooks/useWindowQuery";
interface AddOnInfoProps {
  addOnInfo: AddonType;
}
export const constructBillType = (str: string) => {
  if (str.includes("_")) {
    return str
      .split("_")
      .map((el) => capitalize(el))
      .join(" ");
  } else {
    return str;
  }
};
const AddOnInfo = ({ addOnInfo }: AddOnInfoProps) => {
  const windowWidth = useMediaQuery();

  return (
    <div className="min-h-[200px]  w-full p-8 cursor-pointer font-alliance rounded-sm bg-card ">
      <Typography.Title className="pt-4 whitespace-pre-wrap grid gap-4 !text-[18px] items-center grid-cols-1 md:grid-cols-2">
        <div>Add-On Information</div>
      </Typography.Title>
      <div className=" w-full h-[1.5px] mt-6 bg-card-divider mb-2" />
      <div className="grid  items-center grid-cols-1 md:grid-cols-[repeat(2,_minmax(0,_0.3fr))]">
        <div className="w-[240px]">
          <div className="flex items-center justify-between text-card-text gap-2 mb-1">
            <div className="font-normal whitespace-nowrap leading-4">
              Add-On ID
            </div>
            <div className="flex gap-1 text-card-grey font-menlo">
              {" "}
              <div>
                {createShortenedText(addOnInfo.addon_id, windowWidth >= 2500)}
              </div>
              <CopyText showIcon onlyIcon textToCopy={addOnInfo.addon_id} />
            </div>
          </div>
          <div className="flex items-center text-card-text justify-between mb-1">
            <div className=" font-normal whitespace-nowrap leading-4">
              Price
            </div>
            <div className="flex gap-1">
              {" "}
              <div className="text-gold">{`${addOnInfo.currency?.symbol}${addOnInfo.flat_rate}`}</div>
            </div>
          </div>
        </div>

        <div className="w-[240px]">
          <div className="flex items-center text-card-text justify-between gap-2 mb-1">
            <div className=" font-bold font-alliance whitespace-nowrap leading-4">
              Type
            </div>
            <div className="flex gap-1 ">
              {" "}
              <div className="!text-card-grey">
                {constructBillType(addOnInfo.addon_type)}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between text-card-text gap-2 mb-1">
            <div className="font-bold font-alliance whitespace-nowrap leading-4">
              Billing Frequency
            </div>
            <div>
              <div className="!text-card-grey">
                {constructBillType(addOnInfo.billing_frequency)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
export default AddOnInfo;
