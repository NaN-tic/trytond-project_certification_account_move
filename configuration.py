#The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.model import Model, ModelSQL, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Configuration', 'ConfigurationCompany']


class Configuration:
    __metaclass__ = PoolMeta
    __name__ = 'certification.configuration'

    pending_invoice_account = fields.Function(fields.Many2One(
            'account.account', 'Pending Invoice Account', required=True,
            domain=[
                ('kind', '!=', 'view'),
                ]), 'get_company_config', 'set_company_config')

    @classmethod
    def get_company_config(self, configs, names):
        pool = Pool()
        CompanyConfig = pool.get('certification.configuration-company.company')

        company_id = Transaction().context.get('company')
        company_configs = CompanyConfig.search([
                ('company', '=', company_id),
                ])

        res = {}
        for fname in names:
            res[fname] = {
                configs[0].id: None,
                }
            if company_configs:
                val = getattr(company_configs[0], fname)
                if isinstance(val, Model):
                    val = val.id
                res[fname][configs[0].id] = val
        return res

    @classmethod
    def set_company_config(self, configs, name, value):
        pool = Pool()
        CompanyConfig = pool.get('certification.configuration-company.company')

        company_id = Transaction().context.get('company')
        company_configs = CompanyConfig.search([
                ('company', '=', company_id),
                ])
        if company_configs:
            company_config = company_configs[0]
        else:
            company_config = CompanyConfig(company=company_id)
        setattr(company_config, name, value)
        company_config.save()


class ConfigurationCompany(ModelSQL):
    'Certification Configuration per Company'
    __name__ = 'certification.configuration-company.company'
    _table = 'certification_config-company'

    company = fields.Many2One('company.company', 'Company', required=True,
        select=True)
    pending_invoice_account = fields.Many2One('account.account',
        'Pending Invoice Account',
            domain=[
                ('kind', '!=', 'view'),
                ])
