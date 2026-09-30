import { PageHeading } from '@/components/page-heading';
import { WorkDriveSettings } from '@/components/workdrive-settings';
import { MailSettings } from '@/components/mail-settings';
import { CollectionConfiguration, ProductCategories } from '@/components/product-categories';
import { SettingsNavigation } from '@/components/settings-navigation';
import { IntegrationManagement } from '@/components/integration-management';
const copy:Record<string,[string,string]>={
  'linesheet-templates':['Linesheet templates','Export layout configuration is part of the next presentation layer milestone. Core linesheets already persist and convert to orders.'],
  documents:['Purchase-order documents','Upload and version history are available inside each purchase order.'],
  users:['Users and roles','Use the backend administrator command to create the first user; authenticated user administration is exposed by the users API.'],
  settings:['Operational settings','Sizes and production stages come from the database settings endpoint and retain safe defaults until configured.'],
  mail:['Zoho Mail','Connect and verify the server-side Zoho Mail account used for portal notifications.'],
  general:['General settings','Core organization and operational defaults used throughout the portal.'],
  'email-notifications':['Email notifications','Operational email delivery remains disabled until a workflow and recipient policy are explicitly configured.'],
  security:['Security','Authentication, administrator permissions and integration credentials are enforced by the backend.'],
  categories:['Product categories','Categories and collections are stored separately and retain their existing database-backed sources.']
};
export default async function Workspace({params}:{params:Promise<{section:string}>}){const {section}=await params;if(section==='settings')return <WorkDriveSettings/>;if(section==='mail')return <MailSettings/>;if(section==='integrations')return <IntegrationManagement/>;if(section==='categories')return <><ProductCategories/><CollectionConfiguration/></>;const item=copy[section]||['Workspace','This module is ready for configuration.'];const settingsSection=['general','email-notifications','security'].includes(section);return <>{settingsSection&&<SettingsNavigation/>}<PageHeading eyebrow={settingsSection?'Administration → Settings':'Administration'} title={item[0]} description={item[1]}/><div className="card settings-card"><div className="eyebrow">Current configuration</div><h2>{section==='email-notifications'?'No automatic notifications enabled':section==='security'?'Backend-enforced access':'Operational defaults'}</h2><p className="secondary-copy">{section==='email-notifications'?'Connect Zoho Mail and explicitly configure each business workflow before customer messages are sent.':section==='security'?'Only authenticated administrators with settings permission can manage OAuth connections. Secrets and tokens remain server-side.':'Sizes, production stages and categories continue to use the existing database-backed configuration.'}</p></div></>}
