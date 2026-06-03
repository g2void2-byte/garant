import { describe, expect, it } from "vitest";
import {
  createDealPath,
  newDealToPath,
  normalizeUsernameRef,
  userDetailApiPath,
  userProfilePath,
} from "./usernames";

describe("username route helpers", () => {
  it("normalizes safe username references", () => {
    expect(normalizeUsernameRef(" @alice_1 ")).toBe("alice_1");
    expect(userProfilePath("alice_1")).toBe("/users/alice_1");
    expect(createDealPath("alice-1")).toBe("/create-deal/alice-1");
    expect(newDealToPath("alice_1")).toBe("/deals/new?to=alice_1");
    expect(userDetailApiPath("alice_1")).toBe("api/users/alice_1");
  });

  it.each([
    "",
    "   ",
    "../admin",
    "alice/bob",
    "alice?x=1",
    "alice bob",
    "alice%2fbob",
    "????",
    "a".repeat(65),
  ])("rejects unsafe username reference %s", (value) => {
    expect(normalizeUsernameRef(value)).toBeNull();
    expect(userProfilePath(value)).toBeNull();
    expect(createDealPath(value)).toBeNull();
    expect(newDealToPath(value)).toBeNull();
    expect(userDetailApiPath(value)).toBeNull();
  });
});
