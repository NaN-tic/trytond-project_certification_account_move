# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import work
from . import configuration


def register():
    Pool.register(
        configuration.Configuration,
        configuration.ConfigurationCompany,
        work.Move,
        work.MoveLine,
        work.Certification,
        work.Work,
        work.CertificationLine,
        work.InvoiceMilestone,
        module='project_certification_account_move', type_='model')
