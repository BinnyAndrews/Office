#pragma once

#ifdef SBXPCDLL_PROJECT //do not define for application
#define SBXPCDLL_PORT __declspec(dllexport)
#else
#define SBXPCDLL_PORT __declspec(dllimport)
#endif

#define __needfree // if a BSTR* argument has this specifier, C++ application SHOULD free return BSTR value using SysFreeString.
// if a function has a VARIANT argument, C++ application SHOULD not use it.

//////////////////////////////////////////////////////////////////////////
// API functions
SBXPCDLL_PORT BOOL WINAPI _SetMachineType(long dwMachineNumber, LPCTSTR lpszMachineType);
SBXPCDLL_PORT void WINAPI _DotNET();
SBXPCDLL_PORT BOOL WINAPI _GetEnrollData(long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,long dwBackupNumber,long FAR*  dwMachinePrivilege,VARIANT FAR* dwEnrollData,long FAR* dwPassWord);
SBXPCDLL_PORT BOOL WINAPI _GetEnrollData1(long dwMachineNumber, long dwEnrollNumber, long dwBackupNumber, long FAR* dwMachinePrivilege, long FAR* dwEnrollData, long FAR* dwPassWord);
SBXPCDLL_PORT BOOL WINAPI _SetEnrollData(long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,long dwBackupNumber,long dwMachinePrivilege,VARIANT FAR* dwEnrollData,long dwPassWord);
SBXPCDLL_PORT BOOL WINAPI _SetEnrollData1(long dwMachineNumber, long dwEnrollNumber, long dwBackupNumber, long dwMachinePrivilege, long FAR* dwEnrollData, long dwPassWord);
SBXPCDLL_PORT BOOL WINAPI _DeleteEnrollData(long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,long dwBackupNumber);
SBXPCDLL_PORT BOOL WINAPI _ReadSuperLogData(long dwMachineNumber, BOOL bReadMark);
SBXPCDLL_PORT BOOL WINAPI _GetSuperLogData(long dwMachineNumber,long* dwTMachineNumber,long* dwSEnrollNumber,long* dwSMachineNumber,long* dwGEnrollNumber,long* dwGMachineNumber,long* dwManipulation,long* dwBackupNumber,long* dwYear,long* dwMonth,long* dwDay,long* dwHour,long* dwMinute, long* dwSecond);
SBXPCDLL_PORT BOOL WINAPI _ReadGeneralLogData(long dwMachineNumber, BOOL bReadMark);
SBXPCDLL_PORT BOOL WINAPI _GetGeneralLogData(long dwMachineNumber,long* dwTMachineNumber,long* dwEnrollNumber,long* dwEMachineNumber,long* dwVerifyMode,long* dwYear,long* dwMonth,long* dwDay,long* dwHour,long* dwMinute, long* dwSecond);
SBXPCDLL_PORT BOOL WINAPI _ReadAllSLogData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetAllSLogData(long dwMachineNumber,long* dwTMachineNumber,long* dwSEnrollNumber,long* dwSMachineNumber,long* dwGEnrollNumber,long* dwGMachineNumber,long* dwManipulation,long* dwBackupNumber,long* dwYear,long* dwMonth,long* dwDay,long* dwHour,long* dwMinute, long* dwSecond);
SBXPCDLL_PORT BOOL WINAPI _ReadAllGLogData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetAllGLogData(long dwMachineNumber,long* dwTMachineNumber,long* dwEnrollNumber,long* dwEMachineNumber,long* dwVerifyMode,long* dwYear,long* dwMonth,long* dwDay,long* dwHour,long* dwMinute, long* dwSecond);
SBXPCDLL_PORT BOOL WINAPI _GetDeviceStatus(long dwMachineNumber, long dwStatus, long* dwValue);
SBXPCDLL_PORT BOOL WINAPI _GetDeviceInfo(long dwMachineNumber, long dwInfo, long* dwValue);
SBXPCDLL_PORT BOOL WINAPI _SetDeviceInfo(long dwMachineNumber, long dwInfo, long dwValue);
SBXPCDLL_PORT BOOL WINAPI _EnableDevice(long dwMachineNumber, BOOL bFlag);
SBXPCDLL_PORT BOOL WINAPI _EnableUser(long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,long dwBackupNumber,BOOL bFlag);
SBXPCDLL_PORT BOOL WINAPI _GetDeviceTime(long dwMachineNumber,long* dwYear,long* dwMonth,long* dwDay,long* dwHour,long* dwMinute,long* dwSecond,long* dwDayOfWeek);
SBXPCDLL_PORT BOOL WINAPI _SetDeviceTime(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _PowerOnAllDevice(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _PowerOffDevice(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _ModifyPrivilege(long dwMachineNumber, long dwEnrollNumber, long dwEMachineNumber, long dwBackupNumber, long dwMachinePrivilege);
SBXPCDLL_PORT BOOL WINAPI _ReadAllUserID(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetAllUserID(long dwMachineNumber,long* dwEnrollNumber,long* dwEMachineNumber,long* dwBackupNumber,long* dwMachinePrivilege,long* dwEnable);
SBXPCDLL_PORT BOOL WINAPI _GetSerialNumber(long dwMachineNumber, __needfree BSTR FAR* lpszSerialNumber);
SBXPCDLL_PORT long WINAPI _GetBackupNumber(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetProductCode(long dwMachineNumber, __needfree BSTR FAR* lpszProductCode);
SBXPCDLL_PORT BOOL WINAPI _ClearKeeperData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _EmptyEnrollData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _EmptyGeneralLogData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _EmptySuperLogData(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetUserName(long DeviceKind,long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,VARIANT FAR* lpszUserName);
SBXPCDLL_PORT BOOL WINAPI _GetUserName1(long dwMachineNumber, long dwEnrollNumber, __needfree BSTR FAR* lpszUserName);
SBXPCDLL_PORT BOOL WINAPI _SetUserName(long DeviceKind,long dwMachineNumber,long dwEnrollNumber,long dwEMachineNumber,VARIANT FAR* lpszUserName);
SBXPCDLL_PORT BOOL WINAPI _SetUserName1(long dwMachineNumber, long dwEnrollNumber, BSTR FAR* lpszUserName);
SBXPCDLL_PORT BOOL WINAPI _GetCompanyName(long dwMachineNumber, VARIANT FAR* dwCompanyName);
SBXPCDLL_PORT BOOL WINAPI _GetCompanyName1(long dwMachineNumber, __needfree BSTR FAR* dwCompanyName);
SBXPCDLL_PORT BOOL WINAPI _SetCompanyName(long dwMachineNumber, long vKind, VARIANT FAR* CompanyName);
SBXPCDLL_PORT BOOL WINAPI _SetCompanyName1(long dwMachineNumber, long vKind, BSTR FAR* dwCompanyName);
SBXPCDLL_PORT BOOL WINAPI _GetDoorStatus(long dwMachineNumber, long* dwValue);
SBXPCDLL_PORT BOOL WINAPI _SetDoorStatus(long dwMachineNumber, long dwValue);
SBXPCDLL_PORT BOOL WINAPI _GetBellTime(long dwMachineNumber, long* dwValue, long* dwBellInfo);
SBXPCDLL_PORT BOOL WINAPI _SetBellTime(long dwMachineNumber, long dwValue, long* dwBellInfo);
SBXPCDLL_PORT BOOL WINAPI _ConnectSerial(long dwMachineNumber, long dwCommPort, long dwBaudRate);
SBXPCDLL_PORT BOOL WINAPI _ConnectTcpip(long dwMachineNumber, BSTR FAR* lpszIPAddress, long dwPortNumber, long dwPassWord);
SBXPCDLL_PORT long WINAPI _ConnectP2p(BSTR FAR* lpszMachineID, BSTR FAR* lpszServerIPAddress, long dwServerPortNumber, long dwPassWord, long* pnError);
SBXPCDLL_PORT void WINAPI _Disconnect(long dwMachineNumber);
SBXPCDLL_PORT BOOL WINAPI _GetLastError(long dwMachineNumber, long* dwErrorCode);
SBXPCDLL_PORT BOOL WINAPI _GeneralOperationXML(long dwMachineNumber, __needfree BSTR FAR* lpszReqNResXML );
SBXPCDLL_PORT BOOL WINAPI _GetDeviceLongInfo(long dwMachineNumber, long dwInfo, long FAR* dwValue);
SBXPCDLL_PORT BOOL WINAPI _SetDeviceLongInfo(long dwMachineNumber, long dwInfo, long FAR* dwValue);
SBXPCDLL_PORT BOOL WINAPI _ModifyDuressFP(long dwMachineNumber, long dwEnrollNumber, long dwBackupNumber, long dwDuressSetting);
SBXPCDLL_PORT BOOL WINAPI _GetMachineIP( LPCTSTR lpszProduct, long dwMachineNumber, __needfree BSTR FAR* lpszIPBuf );
SBXPCDLL_PORT BOOL WINAPI _GetDepartName(long dwMachineNumber, long dwDepartNumber, long dwDepartOrDaigong, __needfree BSTR FAR* lpszDepartName);
SBXPCDLL_PORT BOOL WINAPI _SetDepartName(long dwMachineNumber, long dwDepartNumber, long dwDepartOrDaigong, BSTR FAR* lpszDepartName);

//event capture
typedef void (WINAPI *CB_FIRE_EVENT)(void* context, char* xml);

SBXPCDLL_PORT BOOL WINAPI _StartEventCapture( long dwCommType, long dwParam1, long dwParam2, CB_FIRE_EVENT cb, void* context);
SBXPCDLL_PORT void WINAPI _StopEventCapture();

//xml helper interfaces
SBXPCDLL_PORT long WINAPI _XML_ParseInt(BSTR FAR* lpszXML, LPCTSTR lpszTagname);
SBXPCDLL_PORT long WINAPI _XML_ParseLong(BSTR FAR* lpszXML, LPCTSTR lpszTagname);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseBoolean(BSTR FAR* lpszXML, LPCTSTR lpszTagname);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseString(BSTR FAR* lpszXML, LPCTSTR lpszTagname, __needfree BSTR FAR* lpszValue);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseBinaryByte(BSTR FAR* lpszXML, LPCTSTR lpszTagname, BYTE FAR* pData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseBinaryWord(BSTR FAR* lpszXML, LPCTSTR lpszTagname, WORD FAR* pData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseBinaryLong(BSTR FAR* lpszXML, LPCTSTR lpszTagname, long FAR* pData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_ParseBinaryUnicode(BSTR FAR* lpszXML, LPCTSTR lpszTagname, __needfree BSTR FAR* pData, long dwLen);

SBXPCDLL_PORT BOOL WINAPI _XML_AddInt(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, int nValue);
SBXPCDLL_PORT BOOL WINAPI _XML_AddLong(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, long dwValue);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBoolean(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, BOOL bValue);
SBXPCDLL_PORT BOOL WINAPI _XML_AddString(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, LPCTSTR lpszValue);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBinaryByte(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, BYTE FAR* dwData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBinaryWord(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, WORD FAR* dwData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBinaryLong(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, long FAR* dwData, long dwLen);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBinaryUnicode(__needfree BSTR FAR* lpszXML, LPCTSTR lpszTagname, BSTR FAR* lpszData);
SBXPCDLL_PORT BOOL WINAPI _XML_AddBinaryGlyph(__needfree BSTR FAR* lpszXML, LPCTSTR lpszMessage, long width, long height, LPCTSTR lpszFontDescriptor);
