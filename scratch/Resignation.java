package com.register.example.entity;

import jakarta.persistence.*;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "resignations")
public class Resignation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 50)
private String employeeId;

@Column(nullable = false, length = 50)
private String employeeName;

    @Column(nullable = false)
    private LocalDate lastWorkingDay;

    @Column(nullable = false)
    private String reasonForExit;

    private String documentName;

    @Lob
    private byte[] document;

    private boolean hrClearanceDone = false;
    private boolean adminClearanceDone = false;

   @Column(nullable = false, length = 50)
private String status; // Draft, Pending Approval, Approved by Manager and Reviewer, Clearance
                           // Completed, Final Settlement Completed, etc.

    @Lob
    @Column(columnDefinition = "TEXT")
    private String comments;

    @Lob
    @Column(columnDefinition = "TEXT")
    private String managerComment;

    @Lob
    @Column(columnDefinition = "TEXT")
    private String reviewerComment;

    // -------------------- NEW BOOLEAN FLAGS (parallel tracking)
    // --------------------
    @Column(name = "manager_approved")
private Boolean managerApproved = false;

@Column(name = "reviewer_approved")
private Boolean reviewerApproved = false;

@Column
private Boolean hrApproved = false;

@Column(name = "hr_cleared", nullable = false)
private boolean hrCleared = false;

@Column(name = "admin_cleared", nullable = false)
private boolean adminCleared = false;

// --------------------------------------------------------------------------

@Column(name = "it_cleared", nullable = false)
private boolean itCleared = false;

@Column(name = "assigned_manager_id", length = 50)
private String assignedManagerId;

@Column(name = "assigned_reviewer_id", length = 50)
private String assignedReviewerId;

@Column(name = "assigned_hr_id", length = 50)
private String assignedHrId;

@Column(name = "assigned_admin_id", length = 50)
private String assignedAdminId;

@Column(name = "assigned_finance_id", length = 50)
private String assignedFinanceId;

// --- Delegation attribution fields ---
// Who actually performed each action (actor = delegate if delegated, else original approver)

@Column(name = "manager_actor_id", length = 50)
private String managerActorId;

@Column(name = "manager_actor_name", length = 50)
private String managerActorName;

@Column(name = "manager_delegator_id", length = 50)
private String managerDelegatorId;

@Column(name = "manager_delegator_name", length = 50)
private String managerDelegatorName;

@Column(name = "reviewer_actor_id", length = 50)
private String reviewerActorId;

@Column(name = "reviewer_actor_name", length = 50)
private String reviewerActorName;

@Column(name = "reviewer_delegator_id", length = 50)
private String reviewerDelegatorId;

@Column(name = "reviewer_delegator_name", length = 50)
private String reviewerDelegatorName;

@Column(name = "hr_actor_id", length = 50)
private String hrActorId;

@Column(name = "hr_actor_name", length = 50)
private String hrActorName;

@Column(name = "hr_delegator_id", length = 50)
private String hrDelegatorId;

@Column(name = "hr_delegator_name", length = 50)
private String hrDelegatorName;

@Column(name = "admin_actor_id", length = 50)
private String adminActorId;

@Column(name = "admin_actor_name", length = 50)
private String adminActorName;

@Column(name = "admin_delegator_id", length = 50)
private String adminDelegatorId;

@Column(name = "admin_delegator_name", length = 50)
private String adminDelegatorName;

@Column(name = "finance_actor_id", length = 50)
private String financeActorId;

@Column(name = "finance_actor_name", length = 50)
private String financeActorName;

@Column(name = "finance_delegator_id", length = 50)
private String financeDelegatorId;

@Column(name = "finance_delegator_name", length = 50)
private String financeDelegatorName;

    // Getters and Setters
    public String getAssignedManagerId() {
        return assignedManagerId;
    }

    public void setAssignedManagerId(String assignedManagerId) {
        this.assignedManagerId = assignedManagerId;
    }

    public String getAssignedReviewerId() {
        return assignedReviewerId;
    }

    public void setAssignedReviewerId(String assignedReviewerId) {
        this.assignedReviewerId = assignedReviewerId;
    }

    public String getAssignedHrId() {
        return assignedHrId;
    }

    public void setAssignedHrId(String assignedHrId) {
        this.assignedHrId = assignedHrId;
    }

    public String getAssignedAdminId() {
        return assignedAdminId;
    }

    public void setAssignedAdminId(String assignedAdminId) {
        this.assignedAdminId = assignedAdminId;
    }

    public String getAssignedFinanceId() {
        return assignedFinanceId;
    }

    public void setAssignedFinanceId(String assignedFinanceId) {
        this.assignedFinanceId = assignedFinanceId;
    }

    public Boolean getHrApproved() {
        return hrApproved;
    }

    public void setHrApproved(Boolean hrApproved) {
        this.hrApproved = hrApproved;
    }

    // -------------------- Getters & Setters --------------------
    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getEmployeeId() {
        return employeeId;
    }

    public void setEmployeeId(String employeeId) {
        this.employeeId = employeeId;
    }

    public String getEmployeeName() {
        return employeeName;
    }

    public void setEmployeeName(String employeeName) {
        this.employeeName = employeeName;
    }

    public LocalDate getLastWorkingDay() {
        return lastWorkingDay;
    }

    public void setLastWorkingDay(LocalDate lastWorkingDay) {
        this.lastWorkingDay = lastWorkingDay;
    }

    public String getReasonForExit() {
        return reasonForExit;
    }

    public void setReasonForExit(String reasonForExit) {
        this.reasonForExit = reasonForExit;
    }

    public String getComments() {
        return comments;
    }

    public void setComments(String comments) {
        this.comments = comments;
    }

    public String getDocumentName() {
        return documentName;
    }

    public void setDocumentName(String documentName) {
        this.documentName = documentName;
    }

    public byte[] getDocument() {
        return document;
    }

    public void setDocument(byte[] document) {
        this.document = document;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getManagerComment() {
        return managerComment;
    }

    public void setManagerComment(String managerComment) {
        this.managerComment = managerComment;
    }

    public String getReviewerComment() {
        return reviewerComment;
    }

    public void setReviewerComment(String reviewerComment) {
        this.reviewerComment = reviewerComment;
    }

    // New flags
    public Boolean getManagerApproved() {
        return managerApproved;
    }

    public void setManagerApproved(Boolean managerApproved) {
        this.managerApproved = managerApproved;
    }

    public Boolean getReviewerApproved() {
        return reviewerApproved;
    }

    public void setReviewerApproved(Boolean reviewerApproved) {
        this.reviewerApproved = reviewerApproved;
    }

    public boolean getHrCleared() {
        return hrCleared;
    }

    public void setHrCleared(boolean hrCleared) {
        this.hrCleared = hrCleared;
        this.hrClearanceDone = hrCleared;
    }

    public boolean getAdminCleared() {
        return adminCleared;
    }

    public void setAdminCleared(boolean adminCleared) {
        this.adminCleared = adminCleared;
        this.adminClearanceDone = adminCleared;
    }

    public boolean getItCleared() {
        return itCleared;
    }

    public void setItCleared(boolean itCleared) {
        this.itCleared = itCleared;
    }

    // --- Delegation Attribution Getters & Setters ---
    public String getManagerActorId() { return managerActorId; }
    public void setManagerActorId(String managerActorId) { this.managerActorId = managerActorId; }
    public String getManagerActorName() { return managerActorName; }
    public void setManagerActorName(String managerActorName) { this.managerActorName = managerActorName; }
    public String getManagerDelegatorId() { return managerDelegatorId; }
    public void setManagerDelegatorId(String managerDelegatorId) { this.managerDelegatorId = managerDelegatorId; }
    public String getManagerDelegatorName() { return managerDelegatorName; }
    public void setManagerDelegatorName(String managerDelegatorName) { this.managerDelegatorName = managerDelegatorName; }

    public String getReviewerActorId() { return reviewerActorId; }
    public void setReviewerActorId(String reviewerActorId) { this.reviewerActorId = reviewerActorId; }
    public String getReviewerActorName() { return reviewerActorName; }
    public void setReviewerActorName(String reviewerActorName) { this.reviewerActorName = reviewerActorName; }
    public String getReviewerDelegatorId() { return reviewerDelegatorId; }
    public void setReviewerDelegatorId(String reviewerDelegatorId) { this.reviewerDelegatorId = reviewerDelegatorId; }
    public String getReviewerDelegatorName() { return reviewerDelegatorName; }
    public void setReviewerDelegatorName(String reviewerDelegatorName) { this.reviewerDelegatorName = reviewerDelegatorName; }

    public String getHrActorId() { return hrActorId; }
    public void setHrActorId(String hrActorId) { this.hrActorId = hrActorId; }
    public String getHrActorName() { return hrActorName; }
    public void setHrActorName(String hrActorName) { this.hrActorName = hrActorName; }
    public String getHrDelegatorId() { return hrDelegatorId; }
    public void setHrDelegatorId(String hrDelegatorId) { this.hrDelegatorId = hrDelegatorId; }
    public String getHrDelegatorName() { return hrDelegatorName; }
    public void setHrDelegatorName(String hrDelegatorName) { this.hrDelegatorName = hrDelegatorName; }

    public String getAdminActorId() { return adminActorId; }
    public void setAdminActorId(String adminActorId) { this.adminActorId = adminActorId; }
    public String getAdminActorName() { return adminActorName; }
    public void setAdminActorName(String adminActorName) { this.adminActorName = adminActorName; }
    public String getAdminDelegatorId() { return adminDelegatorId; }
    public void setAdminDelegatorId(String adminDelegatorId) { this.adminDelegatorId = adminDelegatorId; }
    public String getAdminDelegatorName() { return adminDelegatorName; }
    public void setAdminDelegatorName(String adminDelegatorName) { this.adminDelegatorName = adminDelegatorName; }

    public String getFinanceActorId() { return financeActorId; }
    public void setFinanceActorId(String financeActorId) { this.financeActorId = financeActorId; }
    public String getFinanceActorName() { return financeActorName; }
    public void setFinanceActorName(String financeActorName) { this.financeActorName = financeActorName; }
    public String getFinanceDelegatorId() { return financeDelegatorId; }
    public void setFinanceDelegatorId(String financeDelegatorId) { this.financeDelegatorId = financeDelegatorId; }
    public String getFinanceDelegatorName() { return financeDelegatorName; }
    public void setFinanceDelegatorName(String financeDelegatorName) { this.financeDelegatorName = financeDelegatorName; }
}