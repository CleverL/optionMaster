# encoding: UTF-8

from __future__ import division

from copy import copy
from collections import OrderedDict

from vnpy.trader.vtConstant import *
from vnpy.trader.vtObject import VtTickData
from vnpy.trader.vtEvent import EVENT_TIMER, EVENT_TRADE, EVENT_ORDER

from .omDate import getTimeToMaturity
from math import (log, pow, sqrt, exp)
import time
# 常量定义
CALL = 1
PUT = -1

# 事件定义
EVENT_OM_LOG = 'eOmLog'


########################################################################
class OmInstrument(VtTickData):
    """交易合约对象"""

    #----------------------------------------------------------------------
    def __init__(self, contract, detail):
        """Constructor"""
        super(OmInstrument, self).__init__()
        
        self.tickInited = False
        
        # 初始化合约信息
        self.symbol = contract.symbol
        self.exchange = contract.exchange
        self.vtSymbol = contract.vtSymbol
    
        self.size = contract.size
        self.priceTick = contract.priceTick
        self.gatewayName = contract.gatewayName
        
        # 中间价
        self.midPrice = EMPTY_FLOAT
        
        # 持仓数据
        self.longPos = 0
        self.shortPos = 0
        self.netPos = 0
        
        if detail:
            self.longPos = detail.longPos
            self.shortPos = detail.shortPos
            self.netPos = self.longPos - self.shortPos
    #----------------------------------------------------------------------
    def newTick(self, tick):
        """行情更新"""
        if not self.tickInited:
            self.date = tick.date
            self.openPrice = tick.openPrice
            self.upperLimit = tick.upperLimit
            self.lowerLimit = tick.lowerLimit
            self.tickInited = True
            
        self.lastPrice = tick.lastPrice
        self.volume = tick.volume
        self.openInterest = tick.openInterest
        self.time = tick.time
        
        self.bidPrice1 = tick.bidPrice1
        self.askPrice1 = tick.askPrice1
        self.bidVolume1 = tick.bidVolume1
        self.askVolume1 = tick.askVolume1
        self.midPrice = (self.bidPrice1 + self.askPrice1) / 2

        self.bidPrice2 =tick.bidPrice2
        self.bidPrice3 =tick.bidPrice3
        self.bidPrice4 =tick.bidPrice4
        self.bidPrice5 =tick.bidPrice5

        self.askPrice2 =tick.askPrice2
        self.askPrice3 =tick.askPrice3
        self.askPrice4 =tick.askPrice4
        self.askPrice5 =tick.askPrice5

        self.bidVolume2 =tick.bidVolume2
        self.bidVolume3 =tick.bidVolume3
        self.bidVolume4 =tick.bidVolume4
        self.bidVolume5 =tick.bidVolume5

        self.askVolume2 =tick.askVolume2
        self.askVolume3 =tick.askVolume3
        self.askVolume4 =tick.askVolume4
        self.askVolume5 =tick.askVolume5

    #----------------------------------------------------------------------
    def newTrade(self, trade):
        """成交更新"""
        if trade.direction is DIRECTION_LONG:
            if trade.offset is OFFSET_OPEN:
                self.longPos += trade.volume
            else:
                self.shortPos -= trade.volume
        else:
            if trade.offset is OFFSET_OPEN:
                self.shortPos += trade.volume
            else:
                self.longPos -= trade.volume
                
        self.calculateNetPos()
       
    #----------------------------------------------------------------------
    def calculateNetPos(self):
        """计算净持仓"""
        newNetPos = self.longPos - self.shortPos
        
        # 检查净持仓是否发生变化
        if newNetPos != self.netPos:
            netPosChanged = True
            self.netPos = newNetPos
        else:
            netPosChanged = False
            
        return netPosChanged


########################################################################
class OmUnderlying(OmInstrument):
    """标的物""" 

    #----------------------------------------------------------------------
    def __init__(self, contract, detail, chainList=None):
        """Constructor"""
        super(OmUnderlying, self).__init__(contract, detail)
        
        # 以该合约为标的物的期权链字典
        self.chainDict = OrderedDict()
        
        # 希腊值
        self.theoDelta = EMPTY_FLOAT    # 理论delta值
        self.posDelta = EMPTY_FLOAT     # 持仓delta值
        
    #----------------------------------------------------------------------
    def addChain(self, chain):
        """添加以该合约为标的的期权链"""
        self.chainDict[chain.symbol] = chain
        
    #----------------------------------------------------------------------
    def newTick(self, tick):
        """行情更新"""
        super(OmUnderlying, self).newTick(tick)
        
        self.theoDelta = self.size * self.midPrice / 100
        
        # 遍历推送自己的行情到期权链中
        for chain in self.chainDict.values():
            chain.newUnderlyingTick()

    #----------------------------------------------------------------------
    def newTrade(self, trade):
        """成交更新"""
        super(OmUnderlying, self).newTrade(trade)
        self.calculatePosGreeks()
    
    #----------------------------------------------------------------------
    def calculatePosGreeks(self):
        """计算持仓希腊值"""
        self.posDelta = self.theoDelta * self.netPos


########################################################################
class OmOption(OmInstrument):
    """期权"""

    #----------------------------------------------------------------------
    def __init__(self, contract, detail, underlying, model, r):
        """Constructor"""
        super(OmOption, self).__init__(contract, detail)
        
        # 期权属性
        self.underlying = underlying    # 标的物对象
        self.k = contract.strikePrice   # 行权价
        self.r = r                      # 利率

        if contract.optionType == OPTION_CALL:
            self.cp = CALL              # 期权类型        
        else:
            self.cp = PUT
            
        self.expiryDate = contract.expiryDate       # 到期日（字符串）
        self.t = getTimeToMaturity(self.expiryDate) # 剩余时间
        # 波动率属性
        self.bidImpv = EMPTY_FLOAT
        self.askImpv = EMPTY_FLOAT
        self.midImpv = EMPTY_FLOAT
    
        # 定价公式
        self.calculatePrice = model.calculatePrice
        self.calculateGreeks = model.calculateGreeks
        self.calculateImpv = model.calculateImpv
    
        # 模型定价
        self.pricingImpv = EMPTY_FLOAT
    
        self.theoPrice = EMPTY_FLOAT    # 理论价
        self.theoDelta = EMPTY_FLOAT    # 合约的希腊值（乘以了合约大小）
        self.theoGamma = EMPTY_FLOAT
        self.theoTheta = EMPTY_FLOAT
        self.theoVega = EMPTY_FLOAT
    
        self.posValue = EMPTY_FLOAT     # 持仓市值
        self.posDelta = EMPTY_FLOAT     # 持仓的希腊值（乘以了持仓）
        self.posGamma = EMPTY_FLOAT
        self.posTheta = EMPTY_FLOAT
        self.posVega = EMPTY_FLOAT 
        
        # 期权链
        self.chain = None
    #----------------------------------------------------------------------
    def calculateOptionImpv(self):
        """计算隐含波动率"""
        underlyingPrice = self.underlying.midPrice

        if not underlyingPrice:
            return        

        # print [self.bidPrice1, underlyingPrice, self.k,self.r, self.t, self.cp]
        self.askImpv = self.calculateImpv(self.askPrice1, underlyingPrice, self.k,
                                          self.r, self.t, self.cp)
        self.bidImpv = self.calculateImpv(self.bidPrice1, underlyingPrice, self.k,
                                          self.r, self.t, self.cp)        
        self.midImpv = (self.askImpv + self.bidImpv) / 2
    
    #----------------------------------------------------------------------
    def calculateTheoGreeks(self):
        """计算理论希腊值"""
        underlyingPrice = self.underlying.midPrice
        if not underlyingPrice:
            print "计算了不"+str(underlyingPrice)
            return
        
        self.theoPrice, delta, gamma, theta, vega = self.calculateGreeks(underlyingPrice, 
                                                                         self.k, 
                                                                         self.r, 
                                                                         self.t, 
                                                                         self.midImpv,
                                                                         self.cp)

        self.theoDelta = delta * self.size
        self.theoGamma = gamma * self.size
        self.theoTheta = theta * self.size
        self.theoVega = vega * self.size


        
    #----------------------------------------------------------------------
    def calculatePosGreeks(self):
        """计算持仓希腊值"""
        self.posValue = self.theoPrice * self.netPos * self.size

        self.posDelta = self.theoDelta * self.netPos
        self.posGamma = self.theoGamma * self.netPos
        self.posTheta = self.theoTheta * self.netPos
        self.posVega = self.theoVega * self.netPos

    #----------------------------------------------------------------------
    def newTick(self, tick):
        """行情更新"""
        super(OmOption, self).newTick(tick)
        # self.r=self.chain.calculateChainRate()
        # print "newTick" + str(self.r)
        # self.calculateOptionImpv()
    
    #----------------------------------------------------------------------
    def newUnderlyingTick(self):
        """标的行情更新"""
        pass
        # self.calculateOptionImpv()
        # self.calculateTheoGreeks()
        # self.calculatePosGreeks()

    #----------------------------------------------------------------------
    def newTrade(self, trade):
        """成交更新"""
        super(OmOption, self).newTrade(trade)
        self.calculatePosGreeks()
        
    #----------------------------------------------------------------------
    def setUnderlying(self, underlying):
        """设置标的物对象"""
        self.underlying = underlying
        

########################################################################
class OmChain(object):
    """期权链"""

    #----------------------------------------------------------------------
    def __init__(self,underlying,symbol, callList, putList):
        """Constructor"""
        self.symbol = symbol
        
        # 原始容器
        self.callDict = OrderedDict()
        self.putDict = OrderedDict()
        self.optionDict = OrderedDict()


        self.underlying=underlying

        # 用来记录平值期权的
        self.chainRate=0

        # 平值期权的CallSymbol
        self.atTheMoneySymbol=None



        # 根据call或者put合约的symbol快速找到相同执行价的put或者call的合约
        self.relativeOption={}


        for index,option in enumerate(callList):
            option.chain = self
            self.callDict[option.symbol] = option
            self.relativeOption[option.symbol]=putList[index]
            self.optionDict[option.symbol] = option

        
        for index,option in enumerate(putList):
            option.chain = self
            self.putDict[option.symbol] = option
            self.relativeOption[option.symbol] = callList[index]
            self.optionDict[option.symbol] = option

        # 持仓数据
        self.longPos = EMPTY_INT
        self.shortPos = EMPTY_INT
        self.netPos = EMPTY_INT
        
        self.posValue = EMPTY_FLOAT
        self.posDelta = EMPTY_FLOAT
        self.posGamma = EMPTY_FLOAT
        self.posTheta = EMPTY_FLOAT
        self.posVega = EMPTY_FLOAT
    
    #----------------------------------------------------------------------
    def calculatePosGreeks(self):
        """计算持仓希腊值"""
        # 清空数据
        self.longPos = 0
        self.shortPos = 0
        self.netPos = 0
        self.posDelta = 0
        self.posGamma = 0
        self.posTheta = 0
        self.posVega = 0
        
        # 遍历汇总
        for option in self.optionDict.values():
            self.longPos += option.longPos
            self.shortPos += option.shortPos
            
            self.posValue += option.posValue
            self.posDelta += option.posDelta
            self.posGamma += option.posGamma
            self.posTheta += option.posTheta
            self.posVega += option.posVega

        
        self.netPos = self.longPos - self.shortPos    
    
    #----------------------------------------------------------------------
    def newTick(self, tick):
        """期权行情更新"""
        option = self.optionDict[tick.symbol]
        # print '期权价格发生变化你应该在这里计算利率'
        option.newTick(tick)
        rate = self.calculateChainRate()
        for option in self.optionDict.values():
            option.r = rate
    #----------------------------------------------------------------------
    def newUnderlyingTick(self):
        """期货行情更新"""
        rate=self.calculateChainRate()
        for option in self.optionDict.values():
            option.r = rate
        self.calculatePosGreeks()

    def calculateChainRate(self):
        """计算利率，选择平值期权的前后两档，五档行情的利率平均值作为最终的利率"""
        s=self.underlying.midPrice
        k=[abs(callOption.k-s) for callOption in self.callDict.values()]
        minIndex= k.index(min(k))
        # print "实值期权位置"+str(minIndex)
        rateArray=[]
        for index in range(-2+minIndex,3+minIndex,1):
            try:
                callPrice = self.callDict.values()[index].midPrice
                putPrice=self.putDict.values()[index].midPrice
                # print self.putDict.values()[index].k
                # print self.callDict.values()[index].k
                # print "call"+str(callPrice)
                # print "put"+str(putPrice)
                f = callPrice - putPrice+ self.putDict.values()[index].k
                r = log(f / self.underlying.midPrice) / self.putDict.values()[index].t
                rateArray.append(r)
            except Exception:
                print "处错误了"
        self.chainRate=round(sum(rateArray)/len(rateArray),4)
        self.atTheMoneySymbol=self.callDict.values()[minIndex].symbol
        return self.chainRate
    #----------------------------------------------------------------------
    def newTrade(self, trade):
        """期权成交更新"""
        option = self.optionDict[trade.symbol]
        
        # 缓存旧数据
        oldLongPos = option.longPos
        oldShortPos = option.shortPos
        
        oldPosValue = option.posValue
        oldPosDelta = option.posDelta
        oldPosGamma = option.posGamma
        oldPosTheta = option.posTheta
        oldPosVega = option.posVega
        
        # 更新到期权s中
        option.newTrade(trade)
        
        # 计算持仓希腊值
        self.longPos = self.longPos - oldLongPos + option.longPos
        self.shortPos = self.shortPos - oldShortPos+ option.shortPos
        self.netPos = self.longPos - self.shortPos
        
        self.posValue = self.posValue - oldPosValue + option.posValue
        self.posDelta = self.posDelta - oldPosDelta + option.posDelta
        self.posGamma = self.posGamma - oldPosGamma + option.posGamma
        self.posTheta = self.posTheta - oldPosTheta + option.posTheta
        self.posVega = self.posVega - oldPosVega + option.posVega


########################################################################
class OmPortfolio(object):
    """持仓组合"""

    #----------------------------------------------------------------------
    def __init__(self,eventEngine, name, model, underlyingList, chainList):
        """Constructor"""
        self.name = name
        self.model = model
        self.eventEngine=eventEngine

        # 原始容器
        self.underlyingDict = OrderedDict()
        self.chainDict = OrderedDict()
        self.optionDict = {}
        self.instrumentDict = {}
        
        for underlying in underlyingList:
            self.underlyingDict[underlying.symbol] = underlying
            
        for chain in chainList:
            self.chainDict[chain.symbol] = chain
            self.optionDict.update(chain.callDict)
            self.optionDict.update(chain.putDict)
        
        self.instrumentDict.update(self.underlyingDict)
        self.instrumentDict.update(self.optionDict)
        
        # 持仓数据
        self.longPos = EMPTY_INT
        self.shortPos = EMPTY_INT
        self.netPos = EMPTY_INT
        
        self.posValue = EMPTY_FLOAT
        self.posDelta = EMPTY_FLOAT
        self.posGamma = EMPTY_FLOAT
        self.posTheta = EMPTY_FLOAT
        self.posVega = EMPTY_FLOAT
        """启动连续计算波动率和持仓统计"""
        self.eventEngine.register(EVENT_TIMER, self.timingCalculate)
    #----------------------------------------------------------------------
    def calculatePosGreeks(self):
        """计算持仓希腊值"""
        self.longPos = 0
        self.shortPos = 0
        self.netPos = 0
        
        self.posValue = 0
        self.posDelta = 0
        self.posGamma = 0
        self.posTheta = 0
        self.posVega = 0
        
        for underlying in self.underlyingDict.values():
            self.posDelta += underlying.posDelta
        
        for chain in self.chainDict.values():
            self.longPos += chain.longPos
            self.shortPos += chain.shortPos
            
            self.posValue += chain.posValue
            self.posDelta += chain.posDelta
            self.posGamma += chain.posGamma
            self.posTheta += chain.posTheta
            self.posVega += chain.posVega
        
        self.netPos = self.longPos - self.shortPos        
    
    #----------------------------------------------------------------------
    def newTick(self, tick):
        """行情推送"""
        symbol = tick.symbol
        if symbol in self.optionDict:
            chain = self.optionDict[symbol].chain
            chain.newTick(tick)
            # self.calculatePosGreeks()  不需要实时计算持仓汇总，定时计算即可
        elif symbol in self.underlyingDict:
            underlying = self.underlyingDict[symbol]
            underlying.newTick(tick)
            # self.calculatePosGreeks()  不需要实时计算持仓汇总，定时计算即可

    def timingCalculate(self,event):
        """定时计算希腊字母和波动率，不实时更新的是因为数据是一条一条返回过来的，比如服务器可能在0.5秒内就返回10多组数据给我，无法实时更新"""
        start = time.time()
        for option in self.optionDict.values():
            option.calculateOptionImpv()
            option.calculateTheoGreeks()
            option.calculatePosGreeks()

        for chain in self.chainDict.values():
            chain.calculatePosGreeks()
        self.calculatePosGreeks()
        end= time.time()
        print end-start
    #----------------------------------------------------------------------
    def newTrade(self, trade):
        """成交推送"""
        symbol = trade.symbol
        if symbol in self.optionDict:
            chain = self.optionDict[symbol].chain
            chain.newTrade(trade)
            self.calculatePosGreeks()
        elif symbol in self.underlyingDict:
            underlying = self.underlyingDict[symbol]
            underlying.newTrade(trade)
            self.calculatePosGreeks()