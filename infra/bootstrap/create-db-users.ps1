# One-time setup: create each service's own user inside its own database.
#
# Run in PowerShell from the repository root, after the first deploy has
# created the SQL server and the three databases:
#
#     .\infra\bootstrap\create-db-users.ps1
#
# It asks for the SQL administrator password and each service's database
# password at hidden prompts (the same values as the GitHub secrets
# SQL_ADMIN_PASSWORD, ANIMALS_DB_PASSWORD, DONATIONS_DB_PASSWORD and
# ENQUIRIES_DB_PASSWORD). Nothing is written to disk or to shell history.
#
# What it does:
#   1. opens the SQL server's firewall to this machine's public IP only;
#   2. in each database, creates the service's contained user (or resets its
#      password if it exists) with db_ddladmin, db_datareader, db_datawriter;
#   3. removes the firewall rule again, whatever happened in step 2.
#
# Tools come from two official Microsoft images, so nothing is installed:
# the Azure CLI (signed in through the alrahmeh-azure-cli volume) and SQL
# Server 2022, whose sqlcmd it borrows.

$ErrorActionPreference = "Stop"

$Subscription = "Azure for Students"
$Prefix = "snsour-ieu2024"
$ResourceGroup = "rg-$Prefix"
$Server = "$Prefix-sql"
$AzureCli = "mcr.microsoft.com/azure-cli:latest"
$SqlTools = "mcr.microsoft.com/mssql/server:2022-CU28-ubuntu-22.04"
$RuleName = "bootstrap-temporary"

function Az {
    docker run --rm -v alrahmeh-azure-cli:/root/.azure $AzureCli az @args --subscription $Subscription
    if ($LASTEXITCODE -ne 0) { throw "az $($args -join ' ') failed" }
}

function Read-Secret([string] $Prompt) {
    $secure = Read-Host -AsSecureString $Prompt
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$AdminPassword = Read-Secret "SQL administrator password (SQL_ADMIN_PASSWORD)"
$Services = [ordered]@{
    animals   = Read-Secret "animals database password (ANIMALS_DB_PASSWORD)"
    donations = Read-Secret "donations database password (DONATIONS_DB_PASSWORD)"
    enquiries = Read-Secret "enquiries database password (ENQUIRIES_DB_PASSWORD)"
}

# This machine's public address, so the rule lets in this machine and nothing else.
$MyIp = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim()
Write-Host "Opening the SQL firewall to $MyIp only"
Az sql server firewall-rule create --resource-group $ResourceGroup --server $Server --name $RuleName --start-ip-address $MyIp --end-ip-address $MyIp --output none

try {
    foreach ($service in $Services.Keys) {
        $user = "${service}_app"
        $database = "$Prefix-$service-db"
        # Contained user: it exists only inside this database and can reach
        # nothing else. Running the script again resets the password instead
        # of failing, so it is safe to repeat.
        $sql = @"
IF USER_ID(N'$user') IS NULL CREATE USER [$user] WITH PASSWORD = N'`$(APP_PASSWORD)';
ELSE ALTER USER [$user] WITH PASSWORD = N'`$(APP_PASSWORD)';
IF IS_ROLEMEMBER(N'db_ddladmin', N'$user') = 0 ALTER ROLE db_ddladmin ADD MEMBER [$user];
IF IS_ROLEMEMBER(N'db_datareader', N'$user') = 0 ALTER ROLE db_datareader ADD MEMBER [$user];
IF IS_ROLEMEMBER(N'db_datawriter', N'$user') = 0 ALTER ROLE db_datawriter ADD MEMBER [$user];
PRINT 'ok: $user in $database';
"@
        # Passwords travel as environment variables of the container: sqlcmd
        # reads SQLCMDPASSWORD for the login and APP_PASSWORD for $(APP_PASSWORD).
        $env:SQLCMDPASSWORD = $AdminPassword
        $env:APP_PASSWORD = $Services[$service]
        docker run --rm -e SQLCMDPASSWORD -e APP_PASSWORD --entrypoint /opt/mssql-tools18/bin/sqlcmd $SqlTools `
            -S "tcp:$Server.database.windows.net,1433" -d $database -U sqladmin -N -b -Q $sql
        if ($LASTEXITCODE -ne 0) { throw "creating $user in $database failed" }
    }
}
finally {
    Remove-Item Env:SQLCMDPASSWORD, Env:APP_PASSWORD -ErrorAction SilentlyContinue
    Write-Host "Removing the temporary firewall rule"
    Az sql server firewall-rule delete --resource-group $ResourceGroup --server $Server --name $RuleName --output none
}

Write-Host "Done. Re-run the failed deploy so the health check can pass."
