# E2E Regression: System Settings & Admin

## Prerequisites
- Admin user logged in
- All services running

---

## TC-SYS-001: System Health Dashboard
**Steps:**
1. Navigate to System page
2. View service health grid

**Expected:**
- All services shown with health status (green/red)
- Status auto-refreshes every 10 seconds
- Each service shows: name, port, status

---

## TC-SYS-002: Kill Switch
**Steps:**
1. Toggle Kill Switch ON

**Expected:**
- All trading halted immediately
- Visual indicator shows trading disabled
- Existing pipelines don't process new trades

2. Toggle Kill Switch OFF

**Expected:**
- Trading resumes
- Pipelines resume processing

---

## TC-SYS-003: Notification Preferences
**Steps:**
1. Toggle email notifications
2. Configure WhatsApp settings
3. Save

**Expected:**
- Preferences persisted
- Email toggle affects notification delivery
- WhatsApp settings saved

---

## TC-ADMIN-001: User Management
**Steps:**
1. Navigate to Admin panel
2. View all users
3. Promote a user to admin
4. Demote an admin

**Expected:**
- User list loads with roles
- Promote/demote actions reflected immediately
- CSV export includes all users

---

## TC-ADMIN-002: Sprint Board
**Steps:**
1. Navigate to Sprint Board
2. Create a new task
3. Drag task between columns
4. Click task to view/edit details
5. Delete task

**Expected:**
- Task created in "Refinement" column
- Drag & drop moves task between: Refinement → Ready → In Progress → Completed
- Task detail page shows all fields
- Delete removes task from board

---

## TC-ADMIN-003: Model Hub
**Steps:**
1. Navigate to Model Hub
2. Register a new model
3. Run health check
4. Toggle model enabled/disabled

**Expected:**
- Model card appears
- Health check shows status
- Toggle enables/disables the model
