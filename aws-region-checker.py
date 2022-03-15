import boto3
from boto3.session import Session
import json, time
from botocore.exceptions import ClientError

# set global vars
global subid
global createfs
global hsmcli
global efscli
global ec2cli
global region
global azname

arr_vols = []

# Created fake SSL keys for HSM init

# Functions
def create_efsmnts(subid, azname, efsid):
    try:
        createmnttarget = efscli.create_mount_target(
            FileSystemId=efsid,
            SubnetId=subid
        )
        efssuccess = createmnttarget['AvailabilityZoneName']
        print("Successfully created EFS mountpoint in " + efssuccess + " -- Green")
    except ClientError as e:
        print("Error creating EFS mount Target in " + subid + " in " + azname)
        print(e.response['Error']['Code'])
        exit

def create_hsmclusters(subid, azname):
    try:
        createhsmcluster = hsmcli.create_cluster(
            SubnetIds=[
                subid,
            ],
            HsmType='hsm1.medium'
        )
        time.sleep(20)
        global clusterid
        clusterid = createhsmcluster['Cluster']['ClusterId']
        print("Created CloudHSMv2 cluster in " + subid + " -- Green")
        time.sleep(20)
        try:
            createhsm = hsmcli.create_hsm(
                ClusterId=clusterid,
                AvailabilityZone=azname
            )
            print("Succesfully created HSM for " + clusterid + " in " + azname)
            time.sleep(20)
        except ClientError as e:
            print(e.response['Error']['Code'])
    except ClientError as e:
        print(e.response['Error']['Code'])

def create_efs():
    try:
        createfs = efscli.create_file_system(
            CreationToken='regioncheck'
        )
        global efsid
        time.sleep(10)
        efsid = createfs['FileSystemId']
    except ClientError as e:
        print("Error creating EFS in " + region)
        print(e.response['Error']['Code'])
        exit

def del_efs(efsid):
    mnttargets = efscli.describe_mount_targets(FileSystemId=efsid)
    mntids = mnttargets['MountTargets']

    for mntid in mntids:
        try:
            efscli.delete_mount_target(
                MountTargetId=mntid['MountTargetId']
            )
        except ClientError as e:
            print(e.response['Error']['Code'])
    print("Pausing to remove mount points...")
    time.sleep(95)
    try:
        efscli.delete_file_system(
            FileSystemId=efsid
        )
    except ClientError as e:
        print(e.response['Error']['Code'])


def del_cloudhsm(clusterid):
    try:
        delhsmdata = hsmcli.delete_hsm(ClusterId=clusterid)
        print("Pausing to remove hsm in " + azname)
        time.sleep(75)
        try:
            delhsmcluster = hsmcli.delete_cluster(ClusterId=clusterid)
            print("Deleting HSM Cluster in " + azname)
        except ClientError as e:
            print(e.response['Error']['Code'])
    except ClientError as e:
        print(e.response['Error']['Code'])

def create_az_vols(azname, voltype):
    try:
        ebs_resp = ec2cli.create_volume(
            AvailabilityZone=azname,
            Size=10,
            VolumeType=voltype,
            iops='300'
        )
    except ClientError as e:
        print(e.response['Error']['Code'])
    return(ebs_resp)


# Set inputs from mapper
with open('aws-region-checker-input.json') as f:
    data = json.load(f)

# set output
#file = open("aws-region-checker-output.csv", "a+")

regionsession = Session()

# Clients for regions
for region in data['regions']:
    ec2cli = boto3.client('ec2', region_name=region)
    efscli = boto3.client('efs', region_name=region)
    hsmcli = boto3.client('cloudhsmv2', region_name=region)
    rdscli = boto3.client('rds', region_name=region)

    print(region)

    #print("======== Checking resources in " + region + " ========")
    # Build Region list of services
    for regionsvc in data['regionsvcs']:
        strregionvar = str(regionsvc + "_regions")
        strregionvar = regionsession.get_available_regions(regionsvc, partition_name='aws', allow_non_regional=False)
        if region in strregionvar:
            print(region + ",service," + regionsvc + ",Green")
        else:
            print(region + ",service," + regionsvc + ",Red")
    
    # create file system in region
    #create_efs()

    # get AZ's
    azs = ec2cli.describe_availability_zones()
    azcount = len(azs['AvailabilityZones'])
    if azcount >= 3:
        print(region + ",Availability Zone," + "Count " + str(azcount) + ",Green")
    else:
        print(region + ",Availability Zone," + "Count " + str(azcount) + ",Red")
    for az in azs['AvailabilityZones']:
        azname = az['ZoneName']
        # Create Ebs Vols
        for voltype in data['voltypes']:
            #create_az_vols(azname, voltype)
            try:
                ebs_resp = ec2cli.create_volume(
                    AvailabilityZone=azname,
                    Size=10,
                    VolumeType=voltype,
                    Iops=300
                )
                arr_vols.append(ebs_resp['VolumeId'])
                print(f"{region}, Volume, {voltype} in {azname}, Green")
            except ClientError as e:
                print(f"{region}, Volume, {voltype} - {e.response['Error']['Code']} in {azname}, Red")

    # build vpc iterator
    vpcs = ec2cli.describe_vpcs()
    vpcresp = vpcs['Vpcs']
    for vpc in vpcresp:
        if vpc["IsDefault"] == True:
            vpcid = vpc['VpcId']
    
    subnetids = ec2cli.describe_subnets(
        Filters=[
            {
                'Name': 'vpc-id',
                'Values': [
                    vpcid,
                ]
            }
        ]
    )
    
    #print("Testing EFS in all AZ's")
    subnetdata = subnetids['Subnets']
    for subnet in subnetdata:
        subid = subnet['SubnetId']
        #create_efsmnts(subid, azname, efsid)
    #print("Validating CloudHSM in all AZ's")
    for subnet in subnetdata:
        subid = subnet['SubnetId']
        #create_hsmclusters(subid, azname)

    # vpc endpoints
    for vpcendpointsvc in data['vpcendpoints']:
        vpcendpointsvcname = str("com.amazonaws." + region + "." + vpcendpointsvc)
        try:
            vpcendpointsvcdata = ec2cli.describe_vpc_endpoint_services(ServiceNames=[vpcendpointsvcname])
            svcdetails = vpcendpointsvcdata['ServiceDetails']
            for svcdetail in svcdetails:
                svcAzCount = len((svcdetail['AvailabilityZones']))
                svcAZ = str(svcdetail['AvailabilityZones'])
                #pprint(svcAZ)
                svcAZout = svcAZ.replace(",", " -")
                svcAZout = svcAZout.replace("[","")
                svcAZout = svcAZout.replace("]", "")
                if svcAzCount >= 3:
                    strout = region + ",vpcendpoint," + vpcendpointsvcname + ",Green," + svcAZout
                    print(strout)
                else:
                    strout = region + ",vpcendpoint," + vpcendpointsvcname + ",Red," + svcAZout
                    print(strout)
        except:
            print(region + ",vpcendpoint," + vpcendpointsvcname + ",Red")

    # clean up
    #print("======== Cleaning up resources in " + region + " ========")
    #del_efs(efsid)
    #del_cloudhsm(clusterid)

    #print("======== Checking instance type availibility for " + region + " ========")
    for instance in data['instancetypes']:
        instanceoutputs = 0
        ec2offerings = ec2cli.describe_instance_type_offerings(
            LocationType='availability-zone',
            Filters=[
                {
                    'Name': 'instance-type',
                    'Values': [
                        instance,
                    ]
                },
            ],
            MaxResults=1000
        )

        instanceoutputs = ec2offerings['InstanceTypeOfferings']
        instanceoutputscount = len(instanceoutputs)
        # init array for AZ print out
        arrAZLoc = []
        for instanceoutput in instanceoutputs:
            arrAZLoc.append(instanceoutput['Location'])
                
        if instanceoutputscount == 0:
            print(region + ",instance," + instance + ",Red,Response " + str(instanceoutputs) + " - InstanceType not in region")
        else:
            #for instanceout in instanceoutputs:
            #instype = instanceout['InstanceType']
            #instloc = instanceout[u'Location']
            strinstancestat = ""
            if len(arrAZLoc) >= 3:
            #if instanceoutputscount >= 3:
                #print(instype + " - " + instloc)
                strinstancestat = "Green," + str(arrAZLoc).replace(",", " - ")
            elif len(arrAZLoc) == 2:
                #print(instype + " - " + instloc + " -- Yellow")
                strinstancestat = "Yellow," + str(arrAZLoc).replace(",", " - ")
                #print(region + ",instance," + instype + ",Yellow, Currently in " + instloc)
                #print(region + ",instance," + instance + ",Yellow," + str(arrAZLoc))
            elif len(arrAZLoc) == 1:
                #print(instype + " - " + instloc + " -- Yellow")
                strinstancestat = "Red," + str(arrAZLoc).replace(",", " - ")
                #print(region + ",instance," + instype + ",Red, Currently in " + instloc)
                #print(region + ",instance," + instance + ",Red," + str(arrAZLoc))
            #elif instanceoutputscount == 0:
            #    print("foo")
                #print(instype + " - " + instloc + " -- Yellow")
            #    strinstancestat = "Red"
            #    print(region + ",instance," + instance + ",Red,Response " + str(instanceoutputs) + " - InstanceType not in region")
            else:
                print("error occurred")
                    
                    
            if strinstancestat:
                print(region + ",instance," + instance + "," + strinstancestat)
                strinstancestat = ""
                instanceoutputscount = None
            elif not strinstancestat:
                print(region + ",instance," + instance + ",Red,Response " + str(instanceoutputs) + " - InstanceType not in region")
                strinstancestat = ""
                instanceoutputscount = None
            else:
                print("error occurred") 

            arrAZLoc.clear()

    # DBInstance check for RDS
    for rdseng in data['rdsengs']:
        for dbeng in data['dbengs']:
            rdsinsts = rdscli.describe_orderable_db_instance_options(Engine=rdseng, DBInstanceClass=dbeng)
            if len(rdsinsts['OrderableDBInstanceOptions']) == 0:
                print(region + ",RDSDBInstance," + rdseng + "," + dbeng + ",Red, Response " + str(rdsinsts['OrderableDBInstanceOptions']) + ", - DB InstanceType not supported or available")
                break
            for rdsinst in rdsinsts['OrderableDBInstanceOptions']:
                respdbeng = rdsinst['Engine']
                respdbengver = rdsinst['EngineVersion']
                respdbinst = rdsinst['DBInstanceClass']
                respdbazs = rdsinst['AvailabilityZones']
                if len(respdbazs) == 3:
                    print(region + ",RDSDBInstance," + respdbeng + "," + respdbengver + "," + respdbinst + ",Green")
                    break
                else:
                    print(region + ",RDSDBInstance," + respdbeng + "," + respdbengver + "," + respdbinst + ",Yellow," + str(respdbazs))
                    break

    # Clean up Volumes
    for vol in arr_vols:
        ec2cli.delete_volume(
            VolumeId=vol
        )
        print(f"Deleted {vol} in {region}")
    arr_vols.clear()