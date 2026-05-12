import random

from AsyncPayments.cryptoBot import AsyncCryptoBot

from misc import config
from utils.database.models import *
from routers.utils.status_deals import *
from routers.utils.status_arbitrs import *



class DB:
    def __init__(self):
        ...


    async def get_or_create_percents(self):
        try:
            percent_id = PercentInvoice.get()
            
        except:
            PercentInvoice.create()

        try:
            percent_id = PercentDeal.get()
        except:
            PercentDeal.create()

    async def get_user_by_username(self, username):
        user = Users.get_or_none(username=username)
        return user
    
    async def create_deal(self, buyer, seller, sum, description, pay_comission, status):
        deal = Deals.create(buyer=buyer, seller=seller, sum=sum, description=description, status=status, pay_comission=pay_comission)
        return deal
    

    async def get_balance_by_username(self, username):
        balance = Users.get(username=username).balance
        return balance
    

    async def get_userid_by_username(self, username):
        user = Users.get_or_none(username=username)
        if user is not None:
            return user.user_id
        
        return user
    

    async def get_deals_by_username(self, username):
        query = (Deals
             .select()
             .where((Deals.buyer == username) | (Deals.seller == username))).order_by().dicts()

        return query

    async def update_status_deal(self, deal_id, status):
        deal = Deals.get(id=deal_id)
        deal.status = status
        deal.save()
        return deal    


    async def get_deal_by_id(self, deal_id):
        deal = Deals.get_or_none(id=deal_id)
        return deal
    
    async def update_deal_confirm(self, deal_id, confirm_user):
        deal = await self.get_deal_by_id(deal_id)
        if confirm_user == deal.buyer:
            deal.confirm_buyer = True
            deal.save()
            user_id = await self.get_userid_by_username(deal.seller)
            return {'position': 'seller', 'user_id': user_id}
        elif confirm_user == deal.seller:
            deal.confirm_seller = True
            deal.save()
            user_id = await self.get_userid_by_username(deal.buyer)
            
            return {'position': 'buyer', 'user_id': user_id}

    async def add_balance_by_username(self, username: str, sum: float):
        user = Users.get(username=username)
        user.balance += float(sum)
        user.save()

    async def remove_balance_by_username(self, username: str, sum: float):
        user = Users.get(username=username)
        user.balance -= float(sum)
        user.save()

    
    async def add_invoice(self, user_id, amount, id_operation):
        Invoices.create(user_id=user_id, amount=amount, id_operation=id_operation)

    async def add_withdraw(self, user_id, amount, id_operation):
        Withdraws.create(user_id=user_id, amount=amount, id_operation=id_operation)



    async def get_admin_level(self, user_id):
        user = Users.get(user_id=user_id)
        return user.admin
    

    async def add_arbitr(self, deal_id, reason, initiator):
        Arbitrs.create(deal_id=deal_id, reason=reason, initiator=initiator)


    async def get_arbitr_deal(self, deal_id):
        arbitr = Arbitrs.get(deal_id=deal_id)
        return arbitr
    
    async def get_all_arbitr(self, verdict = None):
        if verdict is None: ### получаем все арбитражи
            query = Arbitrs.select().dicts()
            return len(query)
        else:
            query = Arbitrs.select().where(Arbitrs.status == verdict).dicts()
            return len(query)
        

    async def get_all_arbitr_info(self):
        arbitr = Arbitrs.select().where(Arbitrs.status == WAIT_CONFIRMATION).dicts()

        return arbitr
    

    async def get_my_arbitr_deals(self, username):
        deals = Arbitrs.select().where(Arbitrs.status == WAIT_VERDICT).where(Arbitrs.arbitr == username).dicts()
        return deals
    
    async def get_my_completed_arbitr_deals(self, username):
        deals = Arbitrs.select().where(Arbitrs.status == VERDICT).where(Arbitrs.arbitr == username).dicts()
        return deals

    async def update_status_arbitr(self, deal_id, status, arbitr_name, verdict = None):
        arbitr = Arbitrs.get(deal_id=deal_id)
        arbitr.status = status
        arbitr.arbitr = arbitr_name
        if verdict is not None:
            arbitr.verdict = verdict
        arbitr.save()


    async def add_arbitration_user(self, username):
        user = Users.get(username=username)
        user.admin = 1
        user.save()

    async def remove_arbitration_user(self, username):
        user = Users.get(username=username)
        user.admin = 0
        user.save()

    async def get_arbitr_or_none(self, username):
        user = Users.get(username=username)

        if user.admin >= 1:
            return user
        
        return None
    

    async def get_stat_by_username(self, username):
        stats = [{'buyer_stat': {}}, {'seller_stat': {}}]
        deals_seller = Deals.select().where(Deals.seller == username).where(Deals.status == SUCCESS).dicts()
        deals_buyer = Deals.select().where(Deals.buyer == username).where(Deals.status == SUCCESS).dicts()

        stats[1]['seller_stat']['sum_sells'] = len(deals_seller)
        stats[1]['seller_stat']['all_sum'] = sum([float(deal['sum']) for deal in deals_seller])
        stats[0]['buyer_stat']['sum_sells'] = len(deals_buyer)
        stats[0]['buyer_stat']['all_sum'] = sum([float(deal['sum']) for deal in deals_buyer])


        return stats
    

    async def get_percent_invoice(self):
        percent = PercentInvoice.get().percent

        return percent
    

    async def update_percent_invoice(self, percent):
        invoice = PercentInvoice.get()
        invoice.percent = percent
        invoice.save()


    async def get_percent_deal(self):
        percent = PercentDeal.get().percent
        return percent
    
    async def update_percent_deal(self, percent):
        deal_percent = PercentDeal.get()
        deal_percent.percent = percent
        deal_percent.save()


    async def add_good_grade(self, username):
        user = Users.get(username=username)
        user.good += 1
        user.save()

    async def add_bad_grade(self, username):
        user = Users.get(username=username)
        user.bad += 1
        user.save()


    async def get_grades(self, username):
        user = Users.get(username=username)
        return {'good': user.good, 'bad': user.bad}


    async def get_deal_by_status(self, status):
        deal = Deals.select().where(Deals.status == status).dicts()
        return deal
    
    async def get_all_users(self):
        users = Users.select().dicts()
        return users

    async def get_users_paginated(self, limit: int, offset: int):
        return Users.select().offset(offset).limit(limit).order_by("id")

    async def count_users(self, ):
        return Users.select().count()

    async def get_all_deals(self):
        deals = Deals.select().order_by()
        return deals

    # Новые методы для настроек вывода:


    async def get_withdraw_mode(self) -> str:
        setting = WithdrawSettings.get_or_none(WithdrawSettings.id == 1)
        if not setting:
            setting = WithdrawSettings.create(mode='auto')
        return setting.mode


    async def set_withdraw_mode(self, mode: str):
        setting = WithdrawSettings.get_or_none(WithdrawSettings.id == 1)
        if setting:
            setting.mode = mode
            setting.save()
        else:
            WithdrawSettings.create(mode=mode)
    # Методы для работы с запросами на вывод (при ручном режиме)


    async def create_withdraw_request(self, user_id: int, amount: float) -> int:
        req = WithdrawRequest.create(user_id=user_id, amount=amount, status='pending')
        return req.id


    async def get_pending_withdraw_requests(self):
        return list(WithdrawRequest.select().where(WithdrawRequest.status == 'pending'))

    async def withdraw_money(self, user_id, amount: float):
        print("TOKEN:", config.cryptobot_token, type(config.cryptobot_token))
        crypto_bot = AsyncCryptoBot(token=config.cryptobot_token)
        spend = f'{user_id}_{random.randint(0, 9999)}'
        print('ХУЙХУЙХУХЙУХЙ')
        print(user_id, amount)
        print(type(spend))

        result = await crypto_bot.transfer(user_id=int(user_id), amount=float(amount), asset='USDT', spend_id=spend)
        return result

    async def approve_withdraw_request(self, request_id: int) -> bool:
        try:
            req = WithdrawRequest.get_by_id(request_id)
        except:
            return False

        # Защита от неправильных типов
        if not isinstance(req.user_id, (int, float)) or not isinstance(req.amount, (int, float)):
            user = Users.get(Users.user_id == req.user_id)
            user.balance += req.amount
            user.save()
            return False

        try:
            result = await self.withdraw_money(req.user_id, req.amount)
        except Exception as e:
            print("Ошибка при выводе средств:", e)
            user = Users.get(Users.user_id == req.user_id)
            user.balance += req.amount
            user.save()
            return False

        if result.status == 'completed':
            req.status = 'approved'
            req.save()
            Withdraws.create(user_id=req.user_id, amount=req.amount, id_operation=result.transfer_id)
            return True
        else:
            req.status = 'failed'
            req.save()
            user = Users.get(Users.user_id == req.user_id)
            user.balance += req.amount
            user.save()
            return False

    async def decline_withdraw_request(self, request_id: int) -> bool:
        print(request_id)
        try:
            req = WithdrawRequest.get(request_id)
        except:
            return False
        req.status = 'declined'
        req.save()
        # Возвращаем средства пользователю
        user = Users.get(Users.user_id == req.user_id)
        user.balance += req.amount
        user.save()
        return True