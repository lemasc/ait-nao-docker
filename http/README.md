# NSPNAO2025 Lab Week 05

ใน Lab นี้ เราจะทำการประเมินประสิทธิภาพของ Web Application ง่าย ๆ ที่ทำงานอยู่บน Docker Container โดยจะจำลองสถานการณ์ที่มีผู้ใช้เข้าใช้งาน พร้อมกันหลาย ๆ คน (Concurrent Users) ด้วยเครื่องมือเทคโนโลยี k6 และวิเคราะห์ผลลัพธ์อย่างเป็นระบบ

**สิ่งที่ต้องมี:**

1. Docker https://www.docker.com/products/docker-desktop/
2. k6 เครื่องมือสำหรับทำ Load Test https://k6.io/docs/getting-started/installation/

## Physical Topology

<figure>
  <img src="image1.png" alt="Diagram showing the physical topology with PC-1 (Load Generator) and PC-2 (Server Node with Docker Environment). PC-1 runs k6 and connects to PC-2's Docker services (Apache, Nginx) via localhost:8080 and localhost:8081. PC-2 also runs monitoring tools (Grafana, Prometheus, cAdvisor) accessible via localhost:3000, localhost:9090, and localhost:8082 respectively.">
  <figcaption>Physical Topology Diagram</figcaption>
</figure>

**1. เครื่องคอมพิวเตอร์ PC-1 (Load Generator Node)**
PC-1 ทำหน้าที่เป็นเครื่องสำหรับสร้างภาระงาน (Load Generator) โดยมีการติดตั้งเครื่องมือ k6 เพื่อใช้ในการจำลองพฤติกรรมของผู้ใช้งานจำนวนมากที่ส่งคำร้องขอ (HTTP Requests) ไปยังเว็บเซิร์ฟเวอร์ที่อยู่บนเครื่อง PC-2 การแยกเครื่องสร้างโหลดออกจากเครื่องที่ให้บริการจริงช่วยลดผลกระทบจากการแย่งใช้ทรัพยากรระบบ (CPU, Memory, Network) ซึ่งอาจทำให้ผลการทดสอบคลาดเคลื่อนได้

**2. เครื่องคอมพิวเตอร์ PC-2 (Server Node)**
PC-2 ทำหน้าที่เป็น Server Node หลักของระบบ โดยมีการใช้งาน Docker Environment เพื่อรัน Service ต่าง ๆ ในรูปแบบ Containerized Architecture ซึ่งประกอบด้วย

- **Apache Web Server** สำหรับให้บริการ HTTP Request
- **Nginx Web Server** สำหรับให้บริการ HTTP Request และใช้ในการเปรียบเทียบ Performance
- **Prometheus** สำหรับ Collect และ Store Metrics ด้าน Performance
- **cAdvisor** สำหรับ Monitor Resource Usage ของ Docker Containers
- **Grafana** สำหรับ Visualization และ Dashboard ของ Metrics

PC-1 และ PC-2 เชื่อมต่อกันผ่าน Network โดย PC-1 จะส่ง HTTP Request ไปยัง Service บน PC-2 ผ่าน Port ที่กำหนด เช่น Apache และ Nginx ขณะที่ Grafana เปิดให้เข้าถึงผ่าน Web Interface เพื่อใช้ในการ Monitor และ Analyze Performance Data ใน Diagram ที่แสดง มีการใช้ `localhost` เป็นตัวอย่างเชิงแนวคิด อย่างไรก็ตาม ในการใช้งานจริงจำเป็นต้องใช้ IP Address ของ PC-2 เพื่อให้การ Communication ระหว่าง Physical Machine เป็นไปอย่างถูกต้อง

---

## ขั้นตอนที่ 1: State Goals and Define the System (กำหนดเป้าหมายและระบบ)

### 1.1 เป้าหมาย (Goals)

- เพื่อเปรียบเทียบประสิทธิภาพ (Comparative Analysis) ระหว่าง **Apache** และ **Nginx** ภายใต้สภาพแวดล้อม Container ที่จำกัดทรัพยากร
- เพื่อวิเคราะห์ความสัมพันธ์ของ Response Time และ Throughput เมื่อปริมาณผู้ใช้งาน (VUs) เพิ่มขึ้น (Scalability)
- เพื่อค้นหาจุดที่ประสิทธิภาพเริ่มลดลง (Knee Point) และจุดที่ระบบไม่สามารถให้บริการได้ (Breaking Point) ของ Web Server ทั้งสองชนิด

### 1.2 ระบบ (System)

- **System Under Test (SUT):**
  - Docker Containers: `httpd:latest` (Apache) และ `nginx:latest` (Nginx)
- **Environment:** Local Machine / VM (Running Docker Engine)
- **Tools:**
  - Load Generator: k6
  - Monitoring Stack: cAdvisor (Collector) + Prometheus (Database) + Grafana (Visualization)

---

## ขั้นตอนที่ 2: List Services and Outcomes (ระบุบริการและผลลัพธ์)

### 2.1 Services (บริการที่ทดสอบ)

- การร้องขอหน้าเว็บเพจหลัก (Static Index Page) ผ่านโปรโตคอล **HTTP GET** ที่ Port 80 (Mapped to 8080)

### 2.2 Outcomes (ผลลัพธ์ที่เป็นไปได้)

- **Done Correctly (สำเร็จ):** ได้รับ `HTTP 200 OK` พร้อม Body ที่ถูกต้อง
- **Cannot Do / Failed (ล้มเหลว):**
  - Refusal: `HTTP 429 Too Many Requests` (เซิร์ฟเวอร์ตอบกลับว่ารับไม่ไหว)
  - Crash/Timeout: `HTTP 502 Bad Gateway`, `HTTP 504 Gateway Timeout`, หรือ Connection Refused

---

## ขั้นตอนที่ 3: Select Metrics (เลือกตัวชี้วัดตาม)

### 3.1 Input (สิ่งที่ป้อนเข้า)

- Metric: `vus` (Virtual Users) - จำนวนผู้ใช้จำลอง ณ เวลานั้นๆ
- Metric: `iterations` - จำนวนรอบการยิง Request ทั้งหมด

### 3.2 Branch: Done Correctly (วัดประสิทธิภาพเมื่อทำงานสำเร็จ)

**A. Time (Response Time):**

- Metric: `http_req_duration` (หน่วย: ms)
- Aggregations: `avg` (ค่าเฉลี่ย), `p(95)` (ที่ 95%), `max` (ค่าสูงสุด)

**B. Rate (Throughput):**

- Metric: `http_reqs` (หน่วย: req/s)
- Focus: Requests per Second (RPS) ที่ทำได้จริง

**C. Resource (Utilization):**

- Metric: `container_cpu_usage_seconds_total` (แปลงเป็น % CPU Usage)
- Metric: `container_memory_usage_bytes` (หน่วย: MB)

### 3.3 Branch: Cannot Do (วัดความล้มเหลว)

- **Error Rate:**
- Metric: `http_req_failed` (คิดเป็น % ของ Request ทั้งหมด)
- Metric: `k6_connection_errors` (จำนวนครั้งที่เชื่อมต่อไม่ได้)

---

## ขั้นตอนที่ 4: List Parameters (ระบุพารามิเตอร์)

เราจะแบ่งพารามิเตอร์ออกเป็น "**ค่าคงที่ (Fixed)**" และ "**ตัวแปร (Factors)**" เพื่อให้เห็นภาพการทดลองชัดเจน

### 4.1 System Parameters (Fixed - ควบคุมให้คงที่)

| Parameter          | ค่าที่กำหนด (Target) | หมายเหตุ                        |
| :----------------- | :------------------- | :------------------------------ |
| OS                 |                      | Host OS                         |
| Hardware           |                      | Host Specs                      |
| CPU Limit (SUT)    | 0.5 vCPU             | จำกัดเพื่อให้เห็นคอขวดชัดเจน    |
| Memory Limit (SUT) | 512 MB               | จำกัดเพื่อให้เห็นผลการจัดการแรม |
| Network            | Docker Bridge        | Default Network                 |

### 4.2 Factors (Variables - ตัวแปรที่จะศึกษา)

| Parameter           | ระดับการทดสอบ (Levels) | รายละเอียด                                                |
| :------------------ | :--------------------- | :-------------------------------------------------------- |
| A. Web Server Image | 2 Levels               | 1. `httpd:latest` (Apache) <br> 2. `nginx:latest` (Nginx) |
| B. Workload (VUs)   | 5 Levels               | 100, 500, 1000, 2500, 5000 VUs                            |

### 4.3 Workload Configuration (Load Profile)

| Parameter           | ค่าที่กำหนด                                      | คำอธิบายโดยสรุป                       |
| :------------------ | :----------------------------------------------- | :------------------------------------ |
| Protocol / Method   | HTTP GET                                         | ส่ง HTTP GET Request ไปยัง Web Server |
| Target Endpoint     | `TARGET_URL` (default: `http://localhost:8080/`) | Endpoint ที่ถูกทดสอบ                  |
| Load Model          | VUs-based (Closed Model)                         | กำหนดโหลดด้วยจำนวน Virtual Users      |
| Virtual Users (VUs) | `TARGET_VUS` (default: 10)                       | จำนวน Concurrent Users                |
| Test Stages         | Warm-up 30s → Steady 60s → Cooldown 30s          | เก็บผลหลักในช่วง Steady State         |
| Total Duration      | 120s ต่อการทดลอง                                 | รวมทุก stages                         |
| Think Time          | Random 0.5-2.0s                                  | จำลองพฤติกรรมผู้ใช้                   |
| Success Criteria    | HTTP 200 OK                                      | ถือเป็น Successful Request            |
| Error Observation   | HTTP ≥500, 429                                   | ใช้ตรวจจับ Failure / Throttling       |

---

## ขั้นตอนที่ 5: Select Factors to Study (เลือกปัจจัยและกำหนดระดับการทดสอบ)

จากการพิจารณา List Parameters ในขั้นตอนก่อนหน้า เราจะเลือกศึกษาปัจจัยที่มี **ผลกระทบสูงสุด (Significant Impact)** ต่อประสิทธิภาพ และกำหนดระดับการทดสอบภายใต้ข้อจำกัดด้านเวลาและทรัพยากรที่มี

### 5.1 ปัจจัยหลัก (Primary Factor)

- **Factor:** จำนวนผู้ใช้จำลอง (Virtual Users - VUs)
  - เป็นปัจจัยภายนอก (Workload) ที่ส่งผลโดยตรงต่อการใช้ทรัพยากร (Resource Utilization) และความเสถียรของระบบมากที่สุด

### 5.2 ปัจจัยควบคุม (Fixed Parameters)

เพื่อให้ผลการทดสอบเชื่อถือได้ เราจะ "ตรึง" ค่าเหล่านี้ไว้ไม่ให้เปลี่ยนแปลง:

- **System:** CPU Limit, Memory Limit (ตาม Step 1)
- **Network:** Localhost / Docker Network
- **Application Logic:** Static Page (Apache Default)

### 5.3 แผนการทดสอบและระดับปัจจัย (Experimental Design & Levels)

เราจะกำหนดระดับ (Levels) ของ VUs เป็น 3 ระดับ เพื่อให้ครอบคลุมสถานะต่างๆ ของระบบ

| Run ID                        | Software | Hardware Spec  | Workload (VUs) | Target Goal       |
| :---------------------------- | :------- | :------------- | :------------- | :---------------- |
| **Block 1: Apache Low Spec**  |          |                |                |                   |
| 1                             | Apache   | Low (0.5 CPU)  | 100            | Baseline          |
| 2                             | Apache   | Low (0.5 CPU)  | 500            | Normal            |
| 3                             | Apache   | Low (0.5 CPU)  | 1000           | Heavy             |
| 4                             | Apache   | Low (0.5 CPU)  | 2500           | Saturation        |
| 5                             | Apache   | Low (0.5 CPU)  | 5000           | Stress            |
| **Block 2: Apache High Spec** |          |                |                |                   |
| 6                             | Apache   | High (1.0 CPU) | 100            | Baseline          |
| 7                             | Apache   | High (1.0 CPU) | 500            | Normal            |
| 8                             | Apache   | High (1.0 CPU) | 1000           | Heavy             |
| 9                             | Apache   | High (1.0 CPU) | 2500           | Scaling Check     |
| 10                            | Apache   | High (1.0 CPU) | 5000           | Stress            |
| **Block 3: Nginx Low Spec**   |          |                |                |                   |
| 11                            | Nginx    | Low (0.5 CPU)  | 100            | Compare w/ Run 1  |
| 12                            | Nginx    | Low (0.5 CPU)  | 500            | Compare w/ Run 2  |
| 13                            | Nginx    | Low (0.5 CPU)  | 1000           | Compare w/ Run 3  |
| 14                            | Nginx    | Low (0.5 CPU)  | 2500           | Compare w/ Run 4  |
| 15                            | Nginx    | Low (0.5 CPU)  | 5000           | Compare w/ Run 5  |
| **Block 4: Nginx High Spec**  |          |                |                |                   |
| 16                            | Nginx    | High (1.0 CPU) | 100            | Compare w/ Run 6  |
| 17                            | Nginx    | High (1.0 CPU) | 500            | Compare w/ Run 7  |
| 18                            | Nginx    | High (1.0 CPU) | 1000           | Compare w/ Run 8  |
| 19                            | Nginx    | High (1.0 CPU) | 2500           | Compare w/ Run 9  |
| 20                            | Nginx    | High (1.0 CPU) | 5000           | Compare w/ Run 10 |

---

## ขั้นตอนที่ 7: Select Workload (กำหนดภาระงาน)

การทดสอบของเราจัดอยู่ในกลุ่ม **Measurement** (การวัดผลจริง) เนื่องจากการทดสอบนี้รันบน **Real Application Binaries** (Apache httpd & Nginx) โดยใช้ **Scripted Clients** (k6) ยิงไปยังระบบจริงที่รันอยู่บน **Local Docker Engine**

### 7.1 Workload Specification (รายละเอียดของภาระงาน)

เรากำหนดหน้าตาของ "Request" ให้เป็นมาตรฐานเดียวกัน เพื่อเปรียบเทียบประสิทธิภาพระหว่าง Web Server ทั้งสองตัว

- **Service Request Type:** `HTTP/1.1 GET`
- **Target Endpoint (Variable by Factor):**
  - Apache: `http://localhost:8080/`
  - Nginx: `http://localhost:8081/`
  - _เหตุผล:_ เป็นการจำลองการเข้าชมหน้าแรก (Landing Page) ซึ่งเป็นพฤติกรรมพื้นฐานที่สุด (Baseline)
- **Payload Size:**
  - **Request:** Small (~100 bytes including Headers)
  - **Response:**
    - Apache: ~45 bytes ("It works!")
    - Nginx: ~612 bytes (Default "Welcome to nginx!" HTML page)
  - _หมายเหตุ:_ แม้ขนาด Response จะต่างกันเล็กน้อย แต่ถือว่าเป็น **Static Content ขนาดเล็ก** เหมือนกัน ซึ่งเพียงพอสำหรับการวัด overhead ของ CPU/Memory
- **Traffic Pattern:**
  - **Arrival Rate:** Constant & Ramping (ปรับระดับ VUs ตาม Step 5: 100 → 5000 VUs)
  - **Think Time:** 0.5-2s (จำลองพฤติกรรมผู้ใช้ที่มีการหยุดอ่านเล็กน้อย)

### 7.2 Technique Selection (การเลือกเทคนิค)

| Parameter          | Your Selection         | คำอธิบาย (Mapping from Theory)                                                                                                                                                      |
| :----------------- | :--------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Technique          | **Measurement**        | เราใช้ **Scripted Clients (k6)** ยิงไปยัง **Real System (Docker Container)** เพื่อวัดค่า End-to-End Performance จริงๆ ไม่ใช่การคำนวณสูตร (Analytic) หรือจำลองเหตุการณ์ (Simulation) |
| Generator          | **k6**                 | เครื่องมือสร้าง Workload (Load Generator) ที่สามารถกำหนด Concurrency (VUs) ได้แม่นยำ                                                                                                |
| Representativeness | **Synthetic Workload** | เราสร้าง Traffic สังเคราะห์ขึ้นมา (Generated Traffic) ไม่ได้ Replay จาก Log จริง แต่จำลองให้ใกล้เคียงกับการเรียกใช้งาน Web Server แบบ Static Content มากที่สุด                      |

---

## ขั้นตอนที่ 8: Design Experiment (ออกแบบและเตรียมการทดลอง)

### 8.1 เตรียมโครงสร้างไฟล์ (File Structure)

ให้สร้างโฟลเดอร์ใหม่ (เช่น `load-test`) และสร้างไฟล์ตามโครงสร้างนี้

```
load-test/
├── docker-compose.yml # ไฟล์หลักสำหรับรัน Apache, Nginx และ Monitoring Stack
├── prometheus.yml # ไฟล์ตั้งค่าให้ Prometheus ดึงข้อมูลจาก cAdvisor
└── script.js # ไฟล์ Script ของ k6
```

### 8.2 สร้างไฟล์ `docker-compose.yml` (System Setup)

ไฟล์นี้จะเตรียม SUT (Apache & Nginx ที่จำกัด Resource ตาม Step 1) และ Monitoring Stack ให้พร้อมใช้งาน สร้างไฟล์ `docker-compose.yml` และวางโค้ดนี้

```yaml
version: "3.8"

services:
# ----------------------------------------------------
# 1. System Under Test (SUT)
# ----------------------------------------------------

# Apache Web Server (Target 1)
apache:
  image: httpd:latest
  container_name: sut-apache
  ports:
    - "8080:80" # เข้าผ่าน http://localhost:8080
  deploy:
    resources:
      limits:
        cpus: "0.50" # จำกัด CPU 0.5 Core
        memory: 512M # จำกัด RAM 512MB
  networks:
    - performance-test-net

# Nginx Web Server (Target 2)
nginx:
  image: nginx:latest
  container_name: sut-nginx
  ports:
    - "8081:80" # เข้าผ่าน http://localhost:8081
  deploy:
    resources:
      limits:
        cpus: "0.50" # จำกัด CPU 0.5 Core
        memory: 512M # จำกัด RAM 512MB
  networks:
    - performance-test-net

# ----------------------------------------------------
# 2. Monitoring Stack (Infrastructure)
# ----------------------------------------------------

# cAdvisor: ตัวดึง Metrics จาก Docker Container
cadvisor:
  image: gcr.io/cadvisor/cadvisor:latest
  container_name: monitor-cadvisor
  ports:
    - "8082:8080"
  volumes:
    - /:/rootfs:ro
    - /var/run:/var/run:ro
    - /sys:/sys:ro
    - /var/lib/docker/:/var/lib/docker:ro
  networks:
    - performance-test-net

# Prometheus: ฐานข้อมูลเก็บ Metrics
prometheus:
  image: prom/prometheus:latest
  container_name: monitor-prometheus
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
  networks:
    - performance-test-net

# Grafana: หน้า Dashboard แสดงผล (User/Pass: admin/admin)
grafana:
  image: grafana/grafana:latest
  container_name: monitor-grafana
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
  networks:
    - performance-test-net

networks:
  performance-test-net:
    driver: bridge
```

### 8.3 สร้างไฟล์ `prometheus.yml` (Monitoring Config)

ไฟล์นี้บอกให้ Prometheus ไปดึงข้อมูลจาก cAdvisor สร้างไฟล์ `prometheus.yml` และวางโค้ดนี้:

```yaml
global:
  scrape_interval: 5s # เก็บข้อมูลทุกๆ 5 วินาที (เพื่อให้เห็นกราฟละเอียดขึ้น)

scrape_configs:
  - job_name: "cadvisor"
    static_configs:
      - targets: ["cadvisor:8080"]
```

### 8.4 สร้างไฟล์ `script.js` (Workload Script)

สร้างไฟล์ `script.js` และวางโค้ดนี้:

```javascript
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
```

### 8.5 เริ่มระบบและเตรียม Dashboard

1. **เปิด Terminal** ในโฟลเดอร์นั้น แล้วรันคำสั่ง `docker-compose up -d`

<figure>
  <img src="image2.png" alt="Terminal output showing Docker pulling images and starting containers for cadvisor, grafana, prometheus, apache, and nginx.">
  <figcaption>Docker Compose Output</figcaption>
</figure>

2. **Check Access:**

   - Apache: เข้า `http://localhost:8080` (ต้องขึ้น It works!)
   - Nginx: เข้า `http://localhost:8081` (ต้องขึ้น Welcome to nginx!)
   - Grafana: เข้า `http://localhost:3000` (Login: admin/admin)

3. **Setup Grafana Dashboard (ทำครั้งแรกครั้งเดียว):**
   - Add Data Source > เลือก **Prometheus** > URL ใส่ `http://prometheus:9090` > Save & Test
   - Import Dashboard > ใส่ ID **14282** (Docker Container Monitoring) > Load > เลือก Prometheus เป็น Data Source > Import (อย่าลืมใส่ Prometheus Data Source ก่อน)

### 8.6 รันการทดลอง (Execution Phase)

ในการวัดประสิทธิภาพ เราจะไม่วัดทันทีที่เริ่มรัน (Cold Start) เพราะผลจะไม่เสถียรครับ

1. **Warm-up (Ramp-up):** ช่วงเวลา "อุ่นเครื่อง"

   - **ทำไม:** เพื่อให้ Application โหลด Caches, สร้าง Connection Pool, และให้ JIT Compiler (ถ้ามี) ทำงานเต็มที่
   - **ระยะเวลาแนะนำ:** สำหรับการเทสสั้นๆ แบบนี้ แนะนำ **30 วินาที** (เพื่อให้กราฟ VUs ไต่ระดับขึ้นไปอย่างนุ่มนวล ไม่กระชากระบบ)

2. **Test Duration (Steady State):** ช่วง "เก็บผลจริง"

   - **ทำไม:** เป็นช่วงที่ Load คงที่ (Constant Load) ข้อมูลที่ได้จะแม่นยำที่สุด
   - **ระยะเวลาแนะนำ:** **60 วินาที**

3. **Countdown (Ramp-down/Cooldown):** ช่วง "ผ่อนเครื่อง"
   - **ทำไม:** เพื่อให้ระบบทยอยปิด Connection อย่างถูกต้อง ไม่เกิด Error ค้าง
   - **ระยะเวลาแนะนำ:** **30 วินาที**

---

## Scenario A: Low Resources (CPU 0.5 Core)

ตั้งต่า Docker: `cpus: 0.5`, `memory: '512M'`

### Part 1: Apache (Port 8080)

```bash
# Run 1-5
k6 run -e VUS=100 -e TARGET_URL=http://localhost:8080 --out csv=apache_0.5_100.csv script.js
k6 run -e VUS=500 -e TARGET_URL=http://localhost:8080 --out csv=apache_0.5_500.csv script.js
k6 run -e VUS=1000 -e TARGET_URL=http://localhost:8080 --out csv=apache_0.5_1000.csv script.js
k6 run -e VUS=2500 -e TARGET_URL=http://localhost:8080 --out csv=apache_0.5_2500.csv script.js
k6 run -e VUS=5000 -e TARGET_URL=http://localhost:8080 --out csv=apache_0.5_5000.csv script.js
```

### Part 2: Nginx (Port 8081)

```bash
# Run 6-10
k6 run -e VUS=100 -e TARGET_URL=http://localhost:8081 --out csv=nginx_0.5_100.csv script.js
k6 run -e VUS=500 -e TARGET_URL=http://localhost:8081 --out csv=nginx_0.5_500.csv script.js
k6 run -e VUS=1000 -e TARGET_URL=http://localhost:8081 --out csv=nginx_0.5_1000.csv script.js
k6 run -e VUS=2500 -e TARGET_URL=http://localhost:8081 --out csv=nginx_0.5_2500.csv script.js
k6 run -e VUS=5000 -e TARGET_URL=http://localhost:8081 --out csv=nginx_0.5_5000.csv script.js
```

---

## Scenario B: High Resources (CPU 1.0 Core)

แก้ไขไฟล์ `docker-compose.yml` เปลี่ยน limits cpus เป็น `'1.0'` แล้ว `docker-compose up -d` ใหม่ก่อนนะครับ

### Part 3: Apache (Port 8080)

```bash
# Run 11-15
k6 run -e VUS=100 -e TARGET_URL=http://localhost:8080 --out csv=apache_1.0_100.csv script.js
k6 run -e VUS=500 -e TARGET_URL=http://localhost:8080 --out csv=apache_1.0_500.csv script.js
k6 run -e VUS=1000 -e TARGET_URL=http://localhost:8080 --out csv=apache_1.0_1000.csv script.js
k6 run -e VUS=2500 -e TARGET_URL=http://localhost:8080 --out csv=apache_1.0_2500.csv script.js
k6 run -e VUS=5000 -e TARGET_URL=http://localhost:8080 --out csv=apache_1.0_5000.csv script.js
```

### Part 4: Nginx (Port 8081)

```bash
# Run 16-20
k6 run -e VUS=100 -e TARGET_URL=http://localhost:8081 --out csv=nginx_1.0_100.csv script.js
k6 run -e VUS=500 -e TARGET_URL=http://localhost:8081 --out csv=nginx_1.0_500.csv script.js
k6 run -e VUS=1000 -e TARGET_URL=http://localhost:8081 --out csv=nginx_1.0_1000.csv script.js
k6 run -e VUS=2500 -e TARGET_URL=http://localhost:8081 --out csv=nginx_1.0_2500.csv script.js
k6 run -e VUS=5000 -e TARGET_URL=http://localhost:8081 --out csv=nginx_1.0_5000.csv script.js
```

## ตารางที่ 8.1: การทดสอบรอบที่ 1

**บันทึกผลการทดสอบเมื่อจำกัด CPU ไว้ที่ 0.5 Core**

| Run | Web Server | Load (VUs) | Total Requests | Success (Count) | Fail (Count) | Mean (ms) (Success) | Std Dev (s) (Success) |
| :-- | :--------- | :--------- | :------------- | :-------------- | :----------- | :------------------ | :-------------------- |
| 1   | Apache     | 100        |                |                 |              |                     |                       |
| 2   | Apache     | 500        |                |                 |              |                     |                       |
| 3   | Apache     | 1000       |                |                 |              |                     |                       |
| 4   | Apache     | 2500       |                |                 |              |                     |                       |
| 5   | Apache     | 5000       |                |                 |              |                     |                       |
| 1   | Nginx      | 100        |                |                 |              |                     |                       |
| 2   | Nginx      | 500        |                |                 |              |                     |                       |
| 3   | Nginx      | 1000       |                |                 |              |                     |                       |
| 4   | Nginx      | 2500       |                |                 |              |                     |                       |
| 5   | Nginx      | 5000       |                |                 |              |                     |                       |

## ตารางที่ 8.2: การทดสอบรอบที่ 1

**บันทึกผลการทดสอบเมื่อจำกัด CPU ไว้ที่ 1.0 Core**

| Run | Web Server | Load (VUs) | Total Requests | Success (Count) | Fail (Count) | Mean (ms) (Success) | Std Dev (s) (Success) |
| :-- | :--------- | :--------- | :------------- | :-------------- | :----------- | :------------------ | :-------------------- |
| 1   | Apache     | 100        |                |                 |              |                     |                       |
| 2   | Apache     | 500        |                |                 |              |                     |                       |
| 3   | Apache     | 1000       |                |                 |              |                     |                       |
| 4   | Apache     | 2500       |                |                 |              |                     |                       |
| 5   | Apache     | 5000       |                |                 |              |                     |                       |
| 1   | Nginx      | 100        |                |                 |              |                     |                       |
| 2   | Nginx      | 500        |                |                 |              |                     |                       |
| 3   | Nginx      | 1000       |                |                 |              |                     |                       |
| 4   | Nginx      | 2500       |                |                 |              |                     |                       |
| 5   | Nginx      | 5000       |                |                 |              |                     |                       |

---

## ขั้นตอนที่ 9: Analyze and Interpret Data (วิเคราะห์และแปลผลข้อมูล)

ใช้ค่าจากตารางผลทดลอง (เช่น Total Requests, Mean, Std Dev) ที่ได้จากขั้นตอนที่ 8 โดยในวิธีคำนวณของแลปกำหนดว่า กำหนดให้ใช้ **Z-distribution** (เพราะ n > 30) และใช้สูตร

$$
CI = \bar{x} \pm z_{1-\alpha/2} \left( \frac{s}{\sqrt{n}} \right)
$$

- $\bar{x}$ bar = Mean response time
- $n$ = Total Requests
- $s$ = Standard deviation estimate
- $z$ ที่ 95% = 1.96

> **สำคัญ:** ก่อนคำนวณให้ทำให้ “หน่วย" ของ Mean กับ Std Dev สอดคล้องกัน (แลปมี Mean เป็น ms และ Std Dev แสดงเป็น s ในตารางผลทดลอง) เพื่อไม่ให้ CI เพี้ยน

### 9.1 รวบรวมข้อมูลดิบ (Data Collection)

สรุปผลลัพธ์ที่ได้จากการทดลองทั้ง 10 รอบลงในตารางนี้ เพื่อให้เห็นภาพรวมเปรียบเทียบกันชัดเจน

**ตาราง 9.1: CI Calculation Results — CPU Limit = 0.5 Core**

| Load (VUs) | Web Server | Mean (ms) | Total Requests (n) | Std Dev (s หรือ ms) | 95% CI (Lower, Upper) | สรุปผลที่ 95% (ทับซ้อน/ไม่ทับซ้อน/ใครดีกว่า) |
| :--------- | :--------- | :-------- | :----------------- | :------------------ | :-------------------- | :------------------------------------------- |
| 100        | Apache     |           |                    |                     |                       |                                              |
| 100        | Nginx      |           |                    |                     |                       |                                              |
| 500        | Apache     |           |                    |                     |                       |                                              |
| 500        | Nginx      |           |                    |                     |                       |                                              |
| 1000       | Apache     |           |                    |                     |                       |                                              |
| 1000       | Nginx      |           |                    |                     |                       |                                              |
| 2500       | Apache     |           |                    |                     |                       |                                              |
| 2500       | Nginx      |           |                    |                     |                       |                                              |
| 5000       | Apache     |           |                    |                     |                       |                                              |
| 5000       | Nginx      |           |                    |                     |                       |                                              |

**ตาราง 9.2: CI Calculation Results — CPU Limit = 1.0 Core**

| Load (VUs) | Web Server | Mean (ms) | Total Requests (n) | Std Dev (s หรือ ms) | 95% CI (Lower, Upper) | สรุปผลที่ 95% (ทับซ้อน/ไม่ทับซ้อน/ใครดีกว่า) |
| :--------- | :--------- | :-------- | :----------------- | :------------------ | :-------------------- | :------------------------------------------- |
| 100        | Apache     |           |                    |                     |                       |                                              |
| 100        | Nginx      |           |                    |                     |                       |                                              |
| 500        | Apache     |           |                    |                     |                       |                                              |
| 500        | Nginx      |           |                    |                     |                       |                                              |
| 1000       | Apache     |           |                    |                     |                       |                                              |
| 1000       | Nginx      |           |                    |                     |                       |                                              |
| 2500       | Apache     |           |                    |                     |                       |                                              |
| 2500       | Nginx      |           |                    |                     |                       |                                              |
| 5000       | Apache     |           |                    |                     |                       |                                              |
| 5000       | Nginx      |           |                    |                     |                       |                                              |

---

## ขั้นตอนที่ 10: Present Results (นำเสนอผล + ข้อจำกัด)

### 10.1 ภาพรวมผลการทดลอง (Overall Results Overview)

จากผลการทดลองพบว่า Performance ของ Apache และ Nginx มีพฤติกรรมแตกต่างกันตามระดับ Load และ Resource Constraint ที่กำหนด โดยเฉพาะในช่วง High Load ซึ่งเป็นช่วงที่ระบบเข้าใกล้ขีดจำกัดของทรัพยากร (System Capacity) ความแตกต่างของ Mean Response Time และ 95% Confidence Interval สามารถสังเกตได้ชัดเจนยิ่งขึ้น การเพิ่ม CPU จาก 0.5 Core เป็น 1.0 Core ส่งผลให้ทั้งสอง Web Server รองรับ Load ได้ดีขึ้น อย่างไรก็ตาม ระดับการปรับตัวและเสถียรภาพของระบบยังคงแตกต่างกันระหว่าง Apache และ Nginx

**ตาราง 10.1: Visual Hypothesis Testing Summary — CPU 0.5 Core**

| Load (VUs) | CI Overlap? (Y/N) | สรุปผล (ไม่ต่าง/ต่างอย่างมีนัย) | ใครดีกว่า (ถ้าต่าง) | หมายเหตุสั้น ๆ (อธิบายจากกราฟ) |
| :--------- | :---------------- | :------------------------------ | :------------------ | :----------------------------- |
| 100        |                   |                                 |                     |                                |
| 500        |                   |                                 |                     |                                |
| 1000       |                   |                                 |                     |                                |
| 2500       |                   |                                 |                     |                                |
| 5000       |                   |                                 |                     |                                |

**ตาราง 10.2: Visual Hypothesis Testing Summary — CPU 1.0 Core**

| Load (VUs) | CI Overlap? (Y/N) | สรุปผล (ไม่ต่าง/ต่างอย่างมีนัย) | ใครดีกว่า (ถ้าต่าง) | หมายเหตุสั้น ๆ (อธิบายจากกราฟ) |
| :--------- | :---------------- | :------------------------------ | :------------------ | :----------------------------- |
| 100        |                   |                                 |                     |                                |
| 500        |                   |                                 |                     |                                |
| 1000       |                   |                                 |                     |                                |
| 2500       |                   |                                 |                     |                                |
| 5000       |                   |                                 |                     |                                |

### การเปรียบเทียบด้วยแผนภาพ (Visual Hypothesis Testing)

<figure>
  <img src="image5.png" alt="Two scatter plots showing Mean Response Time (ms) vs Load (VUs) for Apache and Nginx under CPU 0.5 Core (High Load) and CPU 1 Core (High Load). The plots include 95% Confidence Intervals (error bars).">
  <figcaption>Visual Hypothesis Testing Plots</figcaption>
</figure>

ตารางที่ 10.1 และ 10.2 แสดงผลการเปรียบเทียบ Mean Response Time พร้อม 95% Confidence Interval ระหว่าง Apache และ Nginx ภายใต้ CPU 0.5 Core และ 1.0 Core ตามลำดับ โดยใช้หลัก Visual Hypothesis Testing ดังนี้

- ในกรณีที่ช่วงความเชื่อมั่น (Confidence Interval) **ไม่ทับซ้อนกัน (No Overlap)** สามารถสรุปได้ว่าประสิทธิภาพของ Web Server ทั้งสองแตกต่างกันอย่างมีนัยสำคัญทางสถิติที่ระดับความเชื่อมั่น 95%
- ในกรณีที่ช่วงความเชื่อมั่น **ทับซ้อนกัน (Overlap)** ไม่สามารถสรุปความแตกต่างอย่างมีนัยสำคัญทางสถิติได้

ผลการทดลองแสดงให้เห็นว่าในช่วง Load ต่ำ (เช่น 100 - 500 VUs) Performance ของ Apache และ Nginx มีความใกล้เคียงกัน อย่างไรก็ตาม เมื่อ Load เพิ่มสูงขึ้น (โดยเฉพาะที่ 2500 - 5000 VUs) Nginx มีแนวโน้มให้ Mean Response Time ต่ำกว่าและมี Confidence Interval แคบกว่า ซึ่งสะท้อนถึงความเสถียรของระบบที่ดีกว่า

---

## Capacity Curve & Usable Capacity

<figure>
  <img src="image6.png" alt="Two Capacity Curve plots showing Throughput (req/s) and Response Time (p95, p99 in ms) versus Load (VUs). The plots illustrate the Knee Point, Usable Capacity, and a Response Time Limit (p95 <= 500 ms).">
  <figcaption>Capacity Curve Plots</figcaption>
</figure>

ในส่วนนี้ให้นักศึกษาวิเคราะห์ขีดความสามารถของระบบ (System Capacity) โดยใช้ **Capacity Curve** เพื่อหาจุดทำงานที่เหมาะสม (**Usable Capacity**) และจุดเปลี่ยนพฤติกรรมของระบบ (**Knee Point**)

### ขั้นตอนที่ 1 : สร้าง Capacity Curve

ให้นักศึกษาสร้างกราฟจำนวน 1 ชุดต่อ 1 ระบบที่ทดสอบ โดยประกอบด้วยกราฟย่อย 2 กราฟ

**กราฟที่ 1: Throughput vs Load**

- แกน X: Load (VUs)
- แกน Y: Throughput (requests/sec)

**กราฟที่ 2: Response Time vs Load**

- แกน X: Load (VUs)
- แกน Y: Response Time (ms)
- แสดงอย่างน้อยค่า **p95** (และ p99 ถ้ามี)

> **หมายเหตุ:** ทั้งสองกราฟต้องใช้ค่า Load (VUs) ชุดเดียวกัน

### ขั้นตอนที่ 2: กำหนด Response Time Limit

ให้นักศึกษากำหนด Response Time Threshold ที่ยอมรับได้ เช่น

- **p95 ≤ 500 ms**

จากนั้นให้วาดเส้นแนวนอน (Horizontal Line) บนกราฟ Response Time เพื่อใช้เป็นเกณฑ์ตัดสิน Usable Capacity

### ขั้นตอนที่ 3: ระบุ Knee Point

ให้นักศึกษาพิจารณากราฟทั้งสองร่วมกัน และระบุ **Knee Point** โดยใช้เกณฑ์ดังนี้

- **ก่อน Knee Point:** Throughput เพิ่มขึ้นชัดเจน แต่ Response Time เพิ่มขึ้นช้า
- **หลัง Knee Point:** Throughput เพิ่มขึ้นน้อยหรือคงที่ แต่ Response Time เพิ่มขึ้นอย่างรวดเร็ว

### ขั้นตอนที่ 4: ระบุ Usable Capacity

Usable Capacity คือจุดที่ระบบยังสามารถให้บริการได้โดยไม่เกิน Response Time Limit ที่กำหนด

ให้นักศึกษารายงานค่า:

- Usable Capacity (Load / VUs)
- Usable Capacity (Throughput)

โดยเลือก Load สูงสุดที่ยังคงรักษา p95 ให้อยู่ภายใต้ Threshold

### ขั้นตอนที่ 5: สรุปผล

ให้นักศึกษาสรุปผลการวิเคราะห์ โดยระบุ:

- ค่า **Knee Point** (Load และ Throughput)
- ค่า **Usable Capacity**
- ความสัมพันธ์ระหว่าง Load, Throughput และ Response Time
- เปรียบเทียบพฤติกรรมของระบบที่ทดสอบ (เช่น Apache vs Nginx)
