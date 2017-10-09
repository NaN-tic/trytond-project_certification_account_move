from trytond.model import fields, Workflow
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from decimal import Decimal
from datetime import date

__all__ = ['Certification', 'Move', 'MoveLine', 'Work', 'CertificationLine',
    'InvoiceMilestone']

_ZERO = Decimal('0.0')


class Move:
    __name__ = 'account.move'
    __metaclass__ = PoolMeta

    @classmethod
    def _get_origin(cls):
        origins = super(Move, cls)._get_origin()
        if 'project.work' not in origins:
            origins.append('project.work')
        return origins


class MoveLine:
    __name__ = 'account.move.line'
    __metaclass__ = PoolMeta

    work = fields.Many2One('project.work', 'Work')


class Work:
    __name__ = 'project.work'
    __metaclass__ = PoolMeta

    revenue_moves = fields.One2Many('account.move.line', 'work', 'Move Lines')
    revenue_merited = fields.Function(fields.Numeric('Revenue (M)'),
        'get_merited_amountsl')
    revenue_pending_merited = fields.Function(
        fields.Numeric('Revenue Pending (M)'), 'get_merited_amountsl')

    @classmethod
    def _get_revenue_merited(cls, works, names):
        res = cls.get_merited_amountsl(works, ['revenue_merited'])
        return res['revenue_merited']

    @classmethod
    def _get_revenue_pending_merited(cls, works, names):
        res = cls.get_merited_amountsl(works, ['revenue_pending_merited'])
        return res['revenue_pending_merited']

    @classmethod
    def get_merited_amountsl(cls, works, names=None):
        res = {}
        for name in ['revenue_merited', 'revenue_pending_merited']:
            res[name] = {}

        for work in works:

            merited = sum(l.credit - l.debit
                for l in work.revenue_moves
                if not l.reconciliation)

            res['revenue_pending_merited'][work.id] = (
                Decimal(work.certified_pending_quantity) * work.revenue
                ).quantize(Decimal('.001'))

            res['revenue_merited'][work.id] = merited
        return res


class Certification:
    __name__ = 'project.certification'
    __metaclass__ = PoolMeta

    account_move = fields.Many2One('account.move', 'Account Move')

    @classmethod
    def __setup__(cls):
        super(Certification, cls).__setup__()
        cls._error_messages.update({
                'reconciliated_account': ('Unable to cancel current '
                    'certification since the account move %(move)s '
                    'is already reconciliated'),
                'no_pending_invoice_account': ('Missing Pending Invoice Account '
                    'in Certification Configuration'),
                })

    @classmethod
    @Workflow.transition('confirmed')
    def confirm(cls, certifications):
        super(Certification, cls).confirm(certifications)

        for certification in certifications:
            if not certification._check_parent_invoice_method():
                    continue
            for line in certification.lines:
                move = line.check_acount_stock_move()
                certification.account_move = move
                certification.save()

    def _check_parent_invoice_method(self):
        """
        Checks the invoice method of the subproject parent

        Returns True if the invoice method is not 'manual'
        """
        current = self.work
        while current.parent:
            current = current.parent
        return current.invoice_method != 'manual'

    @classmethod
    def cancel(cls, certifications):
        """
        Cancels a certification. If the certification has not yet been
        reconciled the account move will simply be deleted.
        If it has been reconciled then it will create a new account move
        with inverse lines.
        """
        pool = Pool()
        AccountMove = pool.get('account.move')
        # AccountMoveLine = pool.get('account.move.line')
        # Period = pool.get('account.period')
        Config = pool.get('certification.configuration')
        config = Config(1)

        if not config.pending_invoice_account:
            cls.raise_user_error('no_pending_invoice_account')

        for certification in certifications:
            if not certification.account_move:
                continue
            # Use the account from the product category
            # invoice_account = certification.work.product_goods.account_expense_used

            account_move = certification.account_move
            # Filter lines by account
            move_line, = filter(
                lambda x: x.account == config.pending_invoice_account,
                account_move.lines)

            if not move_line.reconciliation:
                AccountMove.draft([account_move])
                AccountMove.delete([account_move])
                continue

            cls.raise_user_error('reconciliated_account', {
                'move': certification.account_move.rec_name,
                })
            """
            Spoke with Santi, first iteration will be to not allow to cancel
            reconciliated account moves.

            period_id = Period.find(certification.work.company.id,
                date=date.today())
            journal = certification.lines[0]._get_accounting_journal()

            counter_line_1 = AccountMoveLine()
            counter_line_1.account = config.pending_invoice_account
            counter_line_1.debit = move_line.credit
            counter_line_1.credit = move_line.debit
            counter_line_1.journal = journal

            counter_line_2 = AccountMoveLine()
            counter_line_2.account = invoice_account
            counter_line_2.credit = move_line.credit
            counter_line_2.debit = move_line.debit

            move = AccountMove(
                origin=certification.work,
                period=period_id,
                journal=journal,
                date=date.today(),
                lines=[counter_line_1, counter_line_2],
                description='Cancels account move %s' % account_move.rec_name
                )
            move.save()
            AccountMove.post([move])
            # Need to remove reconciliation ? <- How?
            AccountMoveLine.reconcile([move_line, counter_line_1])
            """
        return super(Certification, cls).cancel(certifications)


class CertificationLine:
    __name__ = 'project.certification.line'
    __metaclass__ = PoolMeta

    @classmethod
    def __setup__(cls):
        super(CertificationLine, cls).__setup__()
        cls._error_messages.update({
                'no_pending_invoice_account': ('Missing Pending Invoice Account '
                    'in Certification Configuration'),
                })

    def check_acount_stock_move(self):
        pool = Pool()
        Config = pool.get('certification.configuration')
        Move = pool.get('account.move')

        config = Config(1)
        if not config.pending_invoice_account:
            self.raise_user_error('no_pending_invoice_account')

        with Transaction().set_user(0):
            account_move = self._get_project_account_move(
                config.pending_invoice_account)
            if account_move:
                account_move.save()
                Move.post([account_move])
                return account_move

    def _get_project_account_move(self, pending_invoice_account):
        "Return the account move for the current project"
        pool = Pool()
        Move = pool.get('account.move')
        Period = pool.get('account.period')

        move_lines = self._get_account_move_lines(
            pending_invoice_account)

        if not move_lines:
            return

        accounting_date = self.certification.date
        period_id = Period.find(self.work.company.id, date=accounting_date)

        return Move(
            origin=self.work,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=accounting_date,
            lines=move_lines,
            )

    def _get_accounting_journal(self):
        pool = Pool()
        Journal = pool.get('account.journal')
        journals = Journal.search([('type', '=', 'revenue')], limit=1)
        if journals:
            journal, = journals
        else:
            journal = None
        return journal

    def _get_account_move_lines(self, pending_invoice_account):
        """
        Creates an account move for the current certification
        """
        pool = Pool()
        MoveLine = pool.get('account.move.line')

        if not self.work.product_goods:
            return []

        lines_to_reconcile = MoveLine.search([
            ('work', '=', self.work),
            ('account', '=', pending_invoice_account),
            ('reconciliation', '=', None),
            ])
        unposted_amount = self.work.list_price

        move_lines = []

        if not unposted_amount and not lines_to_reconcile:
            return move_lines

        if unposted_amount:
            invoiced_amount = (unposted_amount * Decimal(
                self.quantity)).quantize(Decimal('.01'))

        else:
            invoiced_amount = unposted_amount

        invoice_account = self.work.product_goods.account_revenue_used

        if invoiced_amount != _ZERO:

            invoiced_line = MoveLine()
            invoiced_line.account = invoice_account
            invoiced_line.work = self.work

            if invoiced_line.account.party_required:
                invoiced_line.party = self.work.party

            invoiced_line.credit = invoiced_amount
            invoiced_line.debit = _ZERO

            self._set_analytic_lines(invoiced_line)

            move_lines.append(invoiced_line)

            pending_line = MoveLine()
            pending_line.account = pending_invoice_account
            pending_line.work = self.work

            if pending_line.account.party_required:
                pending_line.party = self.certification.work.party

            pending_line.debit = invoiced_amount
            pending_line.credit = _ZERO

            move_lines.append(pending_line)

        return move_lines

    def _set_analytic_lines(self, move_line):
        """
        Add to supplied account move line analytic lines based on purchase line
        analytic accounts value
        """
        pool = Pool()
        Date = pool.get('ir.date')

        if (not getattr(self, 'analytic_accounts', False) or
                not self.analytic_accounts.accounts):
            return []

        AnalyticLine = pool.get('analytic_account.line')
        move_line.analytic_lines = []
        for account in self.analytic_accounts.accounts:
            line = AnalyticLine()
            move_line.analytic_lines.append(line)

            line.name = self.work.name
            line.debit = move_line.debit
            line.credit = move_line.credit
            line.account = account
            line.journal = self._get_accounting_journal()
            line.date = Date.today()
            line.reference = self.work.name
            line.party = self.work.party


class InvoiceMilestone:
    __name__ = 'project.invoice_milestone'
    __metaclass__ = PoolMeta

    @classmethod
    def do_invoice(cls, milestones):
        for milestone in [x for x in milestones
                if x.invoice_method == 'remainder']:
            milestone._check_certifications()
        super(InvoiceMilestone, cls).do_invoice(milestones)

    def _check_certifications(self):
        """
        Reconciles and creates the appropiate accounts moves.

        First we fetch all the accounts moves from the project that
        have not yet been reconciled.

        Then we calculate 2 values:

        amount_to_invoice: Is the amount that will be left after reconciling
        the certifications as well as the amount that was remaning from the
        previous invoicing of a milestone (we will get to this later)

            amount_to_invoice = (TOTAL * invoice_percent) - debit

        amount_to_reconcile: Amount that we have to reconcile. This amount
        contains the not reconciliated certifications as well as what was
        remaining from the previous time we invoiced a milestone. This
        remaining amount would be the amount_to_invoice

            amount_to_reconcile = debit

        This method, thus, will create 2 accounts move, THe first one will be
        the reconciliation and the second one will be the amount
        left to invoice

        """
        pool = Pool()
        Move = pool.get('account.move')
        Period = pool.get('account.period')
        MoveLine = pool.get('account.move.line')
        Config = pool.get('certification.configuration')
        config = Config(1)

        invoice_account = self.project.product_goods.account_expense_used

        # Previous move with the remaning amount from last invoice
        previous_moves = self._get_previous_move() or []
        credit = sum(l.credit for l in previous_moves)
        debit = sum(l.debit for l in previous_moves)
        amount_to_invoice = self.project.list_price

        # Amount left to invoice after reconciling the certifications
        # amount_to_invoice = amount_to_invoice - (
        #    self.project.list_price * self.project.percent_progress_amount)
        amount_to_invoice -= abs(credit-debit)
        # Total amount to reconcile
        amount_to_reconcile = abs(credit-debit)

        # Create reconciliations
        pending_invoice = MoveLine()
        pending_invoice.account = config.pending_invoice_account
        if pending_invoice.account.party_required:
            pending_invoice.party = self.project.party

        if amount_to_reconcile > _ZERO:
            pending_invoice.credit = amount_to_reconcile
            pending_invoice.debit = _ZERO
        else:
            pending_invoice.debit = abs(amount_to_reconcile)
            pending_invoice.credit = _ZERO

        counter_invoice = MoveLine()
        counter_invoice.account = invoice_account

        if counter_invoice.account.party_required:
            counter_invoice.party = self.project.party

        if amount_to_reconcile > _ZERO:
            counter_invoice.credit = _ZERO
            counter_invoice.debit = amount_to_reconcile
        else:
            counter_invoice.debit = _ZERO
            counter_invoice.credit = abs(amount_to_reconcile)

        period_id = Period.find(self.project.company.id, date=date.today())
        # TODO: Should ask description?

        move = Move(
            origin=self.project,
            period=period_id,
            journal=self._get_accounting_journal(),
            date=date.today(),
            lines=[pending_invoice, counter_invoice]
            )
        move.save()
        Move.post([move])
        if previous_moves:
            to_reconcile = previous_moves + [list(move.lines)[1]]  # WTF
            MoveLine.reconcile(to_reconcile)

    def _get_accounting_journal(self):
        pool = Pool()
        Journal = pool.get('account.journal')
        journals = Journal.search([('type', '=', 'expense')], limit=1)
        if journals:
            journal, = journals
        else:
            journal = None
        return journal

    def _get_previous_move(self):
        pool = Pool()
        Config = pool.get('certification.configuration')
        config = Config(1)

        m = [x for x in self.project.revenue_moves
             if x.account == config.pending_invoice_account]
        return m

    def _create_remaning(self, amount, period, config_account, invoice_acc):
        pool = Pool()
        Move = pool.get('account.move')
        MoveLine = pool.get('account.move.line')

        pending_invoice = MoveLine()
        pending_invoice.account = config_account

        if pending_invoice.account.party_required:
            pending_invoice.party = self.project.party

        if amount > _ZERO:
            pending_invoice.debit = amount
            pending_invoice.credit = _ZERO
        else:
            pending_invoice.credit = abs(amount)
            pending_invoice.debit = _ZERO

        counter_invoice = MoveLine()
        counter_invoice.account = invoice_acc

        if counter_invoice.account.party_required:
            counter_invoice.party = self.project.party

        if amount > _ZERO:
            counter_invoice.debit = _ZERO
            counter_invoice.credit = amount
        else:
            counter_invoice.credit = _ZERO
            counter_invoice.debit = abs(amount)

        return Move(
            origin=self.project,
            period=period,
            journal=self._get_accounting_journal(),
            date=date.today(),
            lines=[pending_invoice, counter_invoice],
            )
