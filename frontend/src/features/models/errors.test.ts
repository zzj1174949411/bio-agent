import { expect, test } from "vitest";
import { modelFailure } from "./errors";

test("distinguishes provider status from invalid tool output and unknown history", () => {
  expect(modelFailure("MODEL_ACTION_INVALID")).toContain("动作");
  expect(modelFailure("MODEL_CONNECTION_FAILED")).toContain("连接");
  expect(modelFailure("MODEL_PAYMENT_REQUIRED")).toContain("402");
  expect(modelFailure("MODEL_UNAVAILABLE")).toContain("原因尚未定位");
  expect(modelFailure("MODEL_UNAVAILABLE")).not.toContain("余额不足");
});
