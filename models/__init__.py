# models/__init__.py
"""数据模型统一入口：集中导入全部 ORM 模型，保证 db.create_all() / alembic 能发现所有表。"""

from .models import (
    User, Location, Cabinet, Device, Interface, DeviceComponent,
    InventoryTransaction,
    OperationLog, InterfaceRelationship, TopologyLog, TaskSchedule,
    DeviceMonitorLog, Config, MonitorData, AlertRule, AlertEvent,
    InterfaceMonitorData, ConnectionPath, MonitorSetting, MonitorSchedule,
    NotificationConfig, AlertAction, DeviceMonitorConfig, TopologySetting,
    DiscoveryTask, DiscoveryResult, LogicalTopology, TopologyLayout,
    AlertTemplate, AlertEscalation, AlertEscalationLog, AlertSuppression, AlertStatistic,
    MonitorLog, DeviceMonitor, Alert, GlobalSetting, PerformanceMetric,
    MonitoringSetting, ActivityLog,
)

from .maintenance_models import (
    MaintenanceTask, SparePart, Supplier, WorkOrderTemplate,
    KnowledgeArticle, OnCallSchedule, SLAPolicy, Asset, AssetDepreciation,
    AssetLedger, SparePartRequest, SparePartUsage, MaintenanceRecord,
    WorkOrder, InspectionTask, InspectionTemplate, InspectionResult,
    ChangeAffectedDevice, ChangeRequest, CIDependency, ChangeApproval,
    CABConfig, Project, ProblemRecord, KnownError, ServiceCatalog,
    CSIImprovement, EventCorrelationRule, AvailabilityRecord, CSATSurvey,
    ChangeImpactAnalysis,
)

from .monitoring import (
    DeviceConfig, MetricData, AlertHistory, Rule, DeviceHealthScore,
    MaintenanceWindow, AlertEscalationPolicy, SlaUptime,
    AnomalyDetectionRule, AutomatedRemediation,
)

from .config_models import (
    SystemSetting, GlobalParameter, BackupConfig, MonitoringTemplate,
    CollectionSetting, ThresholdProfile, AlertConfigTemplate,
    NotificationTemplate, EscalationPolicy, SNMPSetting, Credential,
    DiscoveryConfig, Role, Permission, UserRole, SystemLog, LogSetting,
    AuditLog, APISetting, IntegrationSetting, WebhookSetting,
)

from .contract_models import Contract, contract_assets
from .license_models import SoftwareLicense, license_devices
from .audit_models import AssetAudit, AssetAuditItem
from .compliance_models import (
    ConfigBaseline, ConfigDrift, ConfigVersion, CompliancePolicy,
    ComplianceCheckResult, BackupVerification,
)
from .report_models import (
    ReportTemplate, ScheduledReport, ReportExecution, ReportFavorite,
    ReportDashboard, ReportDistribution, ComplianceFramework,
    ComplianceEvidence,
)
from .device_group_models import DeviceGroup, device_group_members
from .settings_models import SystemConfig
from .network_models import Vlan, Subnet, IPAddress
from .exec_models import ExecTemplate, ExecTask, ExecTaskDevice, ApiKey
from .oob_models import BmcController, BmcSensor, BmcSensorAlertState, BmcSensorThreshold, BmcPowerLog, BmcEventLog, BmcConfigBackup, BiosTemplate, BmcFirmwareJob, BmcAssetDrift
from .san_models import SanNode, SanLink
from .netflow_models import (
    NetFlowProbe, NetFlowRecord, NetFlowApp,
    NetFlowProtocol, NetFlowDscp, NetFlowAs,
    NetFlowAgg, NetFlowAlert,
)

__all__ = [
    # models.py
    'User', 'Location', 'Cabinet', 'Device', 'Interface', 'DeviceComponent',
    'InventoryTransaction', 'OperationLog', 'InterfaceRelationship',
    'TopologyLog', 'TaskSchedule', 'DeviceMonitorLog', 'Config',
    'MonitorData', 'AlertRule', 'AlertEvent', 'InterfaceMonitorData',
    'ConnectionPath', 'MonitorSetting', 'MonitorSchedule',
    'NotificationConfig', 'AlertAction', 'DeviceMonitorConfig',
    'TopologySetting', 'DiscoveryTask', 'DiscoveryResult',
    'LogicalTopology', 'TopologyLayout', 'AlertTemplate', 'AlertEscalation', 'AlertEscalationLog',
    'AlertSuppression', 'AlertStatistic', 'MonitorLog', 'DeviceMonitor',
    'Alert', 'GlobalSetting', 'PerformanceMetric', 'MonitoringSetting',
    'ActivityLog',
    # maintenance_models.py
    'MaintenanceTask', 'SparePart', 'Supplier', 'WorkOrderTemplate',
    'KnowledgeArticle', 'OnCallSchedule', 'SLAPolicy', 'Asset',
    'AssetDepreciation', 'AssetLedger', 'SparePartRequest', 'SparePartUsage',
    'MaintenanceRecord', 'WorkOrder', 'InspectionTask', 'InspectionTemplate',
    'InspectionResult', 'ChangeAffectedDevice', 'ChangeRequest',
    'CIDependency', 'ChangeApproval', 'CABConfig', 'Project',
    'ProblemRecord', 'KnownError', 'ServiceCatalog', 'CSIImprovement',
    'EventCorrelationRule', 'AvailabilityRecord', 'CSATSurvey',
    'ChangeImpactAnalysis',
    # monitoring.py
    'DeviceConfig', 'MetricData', 'AlertHistory', 'Rule',
    'DeviceHealthScore', 'MaintenanceWindow', 'AlertEscalationPolicy',
    'SlaUptime', 'AnomalyDetectionRule', 'AutomatedRemediation',
    # config_models.py
    'SystemSetting', 'GlobalParameter', 'BackupConfig',
    'MonitoringTemplate', 'CollectionSetting', 'ThresholdProfile',
    'AlertConfigTemplate', 'NotificationTemplate', 'EscalationPolicy',
    'SNMPSetting', 'Credential', 'DiscoveryConfig', 'Role', 'Permission',
    'UserRole', 'SystemLog', 'LogSetting', 'AuditLog', 'APISetting',
    'IntegrationSetting', 'WebhookSetting',
    # contract / license / audit
    'Contract', 'contract_assets', 'SoftwareLicense', 'license_devices',
    'AssetAudit', 'AssetAuditItem',
    # compliance / report / device_group / settings
    'ConfigBaseline', 'ConfigDrift', 'ConfigVersion', 'CompliancePolicy',
    'ComplianceCheckResult', 'BackupVerification', 'ReportTemplate',
    'ScheduledReport', 'ReportExecution', 'ReportFavorite',
    'ReportDashboard', 'ReportDistribution', 'ComplianceFramework',
    'ComplianceEvidence', 'DeviceGroup', 'device_group_members',
    'SystemConfig',
    # network / IPAM
    'Vlan', 'Subnet', 'IPAddress',
    'SanNode', 'SanLink',
    # automation / exec
    'ExecTemplate', 'ExecTask', 'ExecTaskDevice', 'ApiKey',
    'BmcController', 'BmcSensor', 'BmcSensorAlertState', 'BmcSensorThreshold', 'BmcPowerLog', 'BmcEventLog',
    'BmcConfigBackup', 'BiosTemplate', 'BmcFirmwareJob', 'BmcAssetDrift',
    'NetFlowProbe', 'NetFlowRecord', 'NetFlowApp',
    'NetFlowProtocol', 'NetFlowDscp', 'NetFlowAs',
    'NetFlowAgg', 'NetFlowAlert',
]
