import re

with open(r'D:\Xevyte_Connect-main\employee-login-backend2\src\main\java\com\register\example\service\AssetAllocationService.java', 'r', encoding='utf-8') as f:
    code = f.read()

bad_block = '''        // Update asset status and assignment
        asset.setStatus(AssetMaster.Constants.ALLOCATED);
        asset.setAssignedToEmployee(allocation.getEmployee());
        
        // Sync dynamic values
        
        assetMasterRepository.save(asset);

        // Fetch full employee details
        Employee employee = employeeRepository.findByEmployeeId(allocation.getEmployee().getEmployeeId())
                .orElseThrow(() -> new RuntimeException(
                        "Employee not found with ID: " + allocation.getEmployee().getEmployeeId()));'''

good_block = '''        // Update asset status and assignment
        asset.setStatus(AssetMaster.Constants.ALLOCATED);
        asset.setAssignedToEmployee(allocation.getEmployee());
        
        // Sync dynamic values for UI consistency (which prioritizes the map)
        if (asset.getDynamicValues() == null) {
            asset.setDynamicValues(new java.util.HashMap<>());
        }
        putDynamicValueCaseInsensitive(asset.getDynamicValues(), CONST_STATUS, AssetMaster.Constants.ALLOCATED);
        putDynamicValueCaseInsensitive(asset.getDynamicValues(), CONST_ASSET_STATUS, AssetMaster.Constants.ALLOCATED);
        
        assetMasterRepository.save(asset);

        // Fetch full employee details
        Employee employee = employeeRepository.findByEmployeeId(allocation.getEmployee().getEmployeeId())
                .orElseThrow(() -> new RuntimeException(
                        "Employee not found with ID: " + allocation.getEmployee().getEmployeeId()));'''

new_code = code.replace(bad_block, good_block)
with open(r'D:\Xevyte_Connect-main\employee-login-backend2\src\main\java\com\register\example\service\AssetAllocationService.java', 'w', encoding='utf-8') as f:
    f.write(new_code)
