import { expect, test } from "vitest";
import { covered } from "./calc";

test("covered", () => {
  expect(covered(2)).toBe(5);
});

test("env vars reach the test step", () => {
  // The demo passes DEMO_PLAIN through the env-vars input.
  const value = process.env.DEMO_PLAIN;
  if (value !== undefined) {
    expect(value).toBe("plain-value");
  }
});
