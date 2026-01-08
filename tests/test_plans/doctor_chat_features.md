# Doctor Chat Feature Test Plan

## 1. Role Identification Display
- **Test Case 1.1: Platform Doctor Assistant View**
  - **Pre-condition**: Log in as Assistant. Select a patient.
  - **Action**: Observe top tab bar.
  - **Expected**:
    - Left Tab: `PatientName(患者)`
    - Right Tab: `DirectorName(Hospital + Title)` (e.g., `李白(上海九院主任)`)
  
- **Test Case 1.2: Hospital Director View**
  - **Pre-condition**: Log in as Director (Studio Owner). Select a patient.
  - **Action**: Observe top tab bar.
  - **Expected**:
    - Left Tab: `PatientName(患者)`
    - Right Tab: `AssistantName(平台医生)` or `PlatformDoctorName(平台医生)`

## 2. Platform Assistant Functionality
- **Test Case 2.1: Dual Tab Switching**
  - **Action**: Switch between Patient and Internal tabs.
  - **Expected**: Chat content refreshes to show relevant history for each conversation independently.
  
- **Test Case 2.2: Chat with Director (Internal)**
  - **Action**: In Internal tab, send a text message.
  - **Expected**: Message appears in list. Director receives it.
  
- **Test Case 2.3: Chat with Patient**
  - **Action**: In Patient tab, send a text message.
  - **Expected**: Message appears. Patient receives it.

## 3. Hospital Director Functionality
- **Test Case 3.1: Patient Tab Read-Only**
  - **Action**: Select Patient tab.
  - **Expected**:
    - History loads.
    - **Input box is HIDDEN**.
    - Cannot send messages.
  
- **Test Case 3.2: Internal Tab Full Chat**
  - **Action**: Select Internal tab.
  - **Expected**:
    - History loads (chat with Assistant).
    - Input box is VISIBLE.
    - Can send/receive messages.

## 4. Technical Verification
- **Test Case 4.1: API Response**
  - **Action**: Inspect `/doctor/chat/api/context/` response.
  - **Expected**: Returns `patient_conversation_id`, `internal_conversation_id`, `can_send_patient`, `can_send_internal`, and correct labels.
