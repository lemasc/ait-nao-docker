import http from "k6/http";
import { check, sleep } from "k6";

// --- Configuration ---
// รับค่า URL และ VUs จาก Environment Variable (Command Line)
const TARGET_URL = __ENV.TARGET_URL || "http://localhost:8080";
const TARGET_VUS = __ENV.VUS ? parseInt(__ENV.VUS) : 10; // Default 10 ถ้าไม่ใส่

// กำหนดค่าช่วง Think Time แบบสุ่ม (ของคุณ)
const THINK_TIME_MIN = __ENV.THINK_TIME_MIN
  ? parseFloat(__ENV.THINK_TIME_MIN)
  : 0.5;
const THINK_TIME_MAX = __ENV.THINK_TIME_MAX
  ? parseFloat(__ENV.THINK_TIME_MAX)
  : 2.0;

function randomThinkTime(min, max) {
  const low = Math.max(0, Math.min(min, max));
  const high = Math.max(min, max);
  return low + Math.random() * (high - low);
}

// --- Test Lifecycle (Stages) ---
export const options = {
  // ไม่ต้องใช้ --vus หรือ --duration ใน command line แล้ว เพราะเรากำหนดตรงนี้
  stages: [
    // 1. Warm-up: ไต่ระดับจาก 0 ถึง TARGET_VUS ใน 30 วินาที
    { duration: "30s", target: TARGET_VUS },

    // 2. Steady State: แช่จำนวน VUs ไว้นิ่งๆ เพื่อวัดผล 60 วินาที (ช่วงเก็บผลจริง)
    { duration: "1m", target: TARGET_VUS },

    // 3. Cooldown: ลดระดับลงเหลือ 0 ใน 30 วินาที
    { duration: "30s", target: 0 },
  ],
};

export default function () {
  // 1. Send Request
  const res = http.get(TARGET_URL);

  // 2. Validate Outcome
  check(res, {
    "is status 200 (Done Correctly)": (r) => r.status === 200,
    "is status 50x (Crash/Fail)": (r) => r.status >= 500,
    "is status 429 (Refusal)": (r) => r.status === 429,
  });

  // 3. Think Time (Random)
  sleep(randomThinkTime(THINK_TIME_MIN, THINK_TIME_MAX));
}
