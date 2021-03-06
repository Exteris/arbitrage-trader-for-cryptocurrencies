import logging
import time
from multiprocessing import Pool
from client import huobi_pro_client, poloniex_client
from config import config_trader, config_coin

logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %H:%M:%S', level=logging.WARNING)


class PremiumValueException(Exception):
    pass


def get_price_in_size(market='', currency_pair='', size='', margin='0'):

    """
    Return avgPrice given size.
    :param market: 'huobi_pro', 'poloniex'
    :param currency_pair: string, standard currency pair format, e.g. 'ETH/BTC', refer to coin configuration
    :param size: string, default value is from trader configuration
    :param margin: string, default is 0, to add additional size (margin)
    :return: dict, {'bid': string, 'ask': string}
    """

    # raise BaseException('test error')

    base_currency, quote_currency = currency_pair.split('/')
    res = {}

    if not size:
        size = config_trader.get_trade_size(base_currency)

    if margin != 0:
        size = '%.8f' % (float(size) * (1 + float(margin)))

    if market == 'huobi_pro':
        client = huobi_pro_client.HuobiProClient(base_currency=base_currency, quote_currency=quote_currency)
        res['bid'] = client.get_average_bids_given_size(size)[1]
        res['ask'] = client.get_average_asks_given_size(size)[1]
    elif market == 'poloniex':
        base_currency = config_coin.currency_name_standard_to_poloniex(base_currency)
        quote_currency = config_coin.currency_name_standard_to_poloniex(quote_currency)
        client = poloniex_client.PoloniexClient()
        res = client.get_ticker_with_size(base_currency=base_currency, quote_currency=quote_currency,
                                          base_currency_trade_size=size)

    return res


def get_prices_mp(size='', currency_pair_first=False):

    """
    Get all prices in all currency_pairs in all markets
    :return: dict[market_name][currency_pair]['bid'/'ask']
    """

    res = {}

    pool = Pool()

    if not currency_pair_first:
        for market in config_trader.market_list:
            res[market] = {}
            for currency_pair in config_trader.trade_currency_pairs:
                res[market][currency_pair] = \
                    pool.apply_async(get_price_in_size,
                                     kwds={'market': market, 'currency_pair': currency_pair, 'size': size})
    else:
        for currency_pair in config_trader.trade_currency_pairs:
            res[currency_pair] = {}
            for market in config_trader.market_list:
                res[currency_pair][market] = \
                    pool.apply_async(get_price_in_size,
                                     kwds={'market': market, 'currency_pair': currency_pair, 'size': size})

    pool.close()
    # time.sleep(5)

    for k1 in res:
        for k2 in res[k1]:
            try:
                res[k1][k2] = res[k1][k2].get(timeout=5)
            except BaseException as err:
                logging.warning('Error in getting prices. (%s, %s)' % (k1, k2))
                # del res[k1]
                # break
                # raise err
                pass

    pool.terminate()
    pool.join()

    subres = {}
    failed = []
    for k1 in res:
        all_ok = True
        for k2 in res[k1]:
            if not isinstance(res[k1][k2], dict):
                failed.append(k1)
                all_ok = False
                break
        if all_ok:
            subres[k1] = res[k1]

    logging.warning(res)
    logging.warning(subres)
    logging.warning('Getting prices: %d/%d success. Failed ones: %s' % (len(subres), len(res), failed))
    return subres


def get_premium_mp(currency_pair='', size=''):

    """
    Return the premium and the market names
    :param currency_pair: string
    :param size: string
    :return: dict of [premium, market_hi, market_lo],
            {
                premium: string,
                market_hi: string,
                market_lo: string
            }
            s.t. highest bid price in market_hi > lowest ask price in market_lo,
            a.k.a. sell in market_hi and buy in market_lo to make profit of premium
    """

    # premium = highest bid in a market > lowest ask in another market
    # to get premium, we need to find the highest bid in all markets and lowest ask in all markets

    # find highest bid and lowest ask in all markets
    highest_bid = None
    lowest_ask = None
    market_hi = None
    market_lo = None

    market_list = config_trader.market_list

    result = dict()
    pool = Pool()
    for market in market_list:
        result[market] = pool.apply_async(get_price_in_size,
                                          kwds={'market': market, 'currency_pair': currency_pair, 'size': size})
    pool.close()

    # print(result)

    for market in market_list:
        try:
            price = result[market].get(timeout=5)
        except BaseException as err:
            raise err
        if (not highest_bid) or (float(price['bid']) > float(highest_bid)):
            highest_bid = price['bid']
            market_hi = market
        if (not lowest_ask) or (float(price['ask']) < float(lowest_ask)):
            lowest_ask = price['ask']
            market_lo = market

    pool.terminate()
    pool.join()

    premium = float(highest_bid)/float(lowest_ask)-1
    if market_hi == market_lo and premium > 0:
        raise PremiumValueException('Premium value error! In market %s, highest bid is higher than the lowest ask!'
                                    % market_hi)
    if premium > 0.2:
        raise PremiumValueException('Premium value possible error! Premium: %.4f, %s, %s' %
                                    (premium, market_hi, market_lo))

    res = dict()
    res['premium'] = "%.4f" % premium
    res['market_hi'] = market_hi
    res['market_lo'] = market_lo
    return res


def cal_premium(prices):

    # premium = highest bid in a market > lowest ask in another market
    # to get premium, we need to find the highest bid in all markets and lowest ask in all markets

    # find highest bid and lowest ask in all markets
    highest_bid = None
    lowest_ask = None
    market_hi = None
    market_lo = None

    market_list = config_trader.market_list

    for market in market_list:
        price = prices[market]
        if (not highest_bid) or (float(price['bid']) > float(highest_bid)):
            highest_bid = price['bid']
            market_hi = market
        if (not lowest_ask) or (float(price['ask']) < float(lowest_ask)):
            lowest_ask = price['ask']
            market_lo = market
    premium = float(highest_bid) / float(lowest_ask) - 1
    if market_hi == market_lo and premium > 0:
        raise PremiumValueException('Premium value error! In market %s, highest bid is higher than the lowest ask!'
                                    % market_hi)
    if premium > 0.2:
        raise PremiumValueException('Premium value possible error! Premium: %.4f, %s, %s' %
                                    (premium, market_hi, market_lo))

    res = dict()
    res['premium'] = "%.4f" % premium
    res['market_hi'] = market_hi
    res['market_lo'] = market_lo
    return res


def cal_premiums(prices):

    res = {}

    for currency_pair in prices:
        res[currency_pair] = cal_premium(prices[currency_pair])

    return res


def get_premiums_mp():

    return cal_premiums(get_prices_mp(currency_pair_first=True))


if __name__ == '__main__':
    pass
    # print(get_prices_mp())
    # print(get_price_in_size('poloniex', currency_pair='BCC/BTC'))
    # print(get_premiums_mp())
    print(get_premium_mp('BCC/BTC'))
    # print(get_price_in_size(market='huobi_pro', currency_pair='ETH/BTC'))
