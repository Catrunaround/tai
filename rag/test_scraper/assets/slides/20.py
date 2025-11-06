class Place:
    """
    >>> places = [Place(x*2) for x in range(10)]
    >>> places[4].print_history()
    8
    6
    4
    2
    0
    >>> Place.last.print_history()
    18
    16
    14
    12
    10
    8
    6
    4
    2
    0
    """
    last = None
    def __init__(self, n):
        self.name = n
        self.then = Place.last
        Place.last = self

    def print_history(self):
        print(self.name)
        if self.then is not None:
            #self.then.print_history()
            Place.print_history(self.then)

def add_country_to_all(country: str):
    Place.country = country


# Close friends

class Friend:
    """
    >>> john = Friend('John')
    >>> kay = Friend('Kay')
    >>> josh = Friend('Josh')
    >>> john.talk(kay)
    >>> josh.talk(kay)
    >>> john.talked_to
    0
    >>> kay.talked_to
    2
    >>> kay.is_bestie(josh)
    True
    >>> kay.is_bestie(john)
    False
    """

    def __init__(self, name: str):
        self.name = name
        self.just_talked = None
        self.talked_to = 0
       
    def talk(self, other):
        self.just_talked = other
        other.just_talked = self
        other.talked_to += 1

    def is_bestie(self, other):
        return self.just_talked is other and other.just_talked is self

    def has_bestie(self):
        return self.just_talked and self.is_bestie(self.just_talked)
    
# Where's Waldo

class Exhibit():
    """
    >>> FerrisWheel(Carousel.x).get_name()
    Waldo
    """
    z = '!'
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def get_name(self):
        return self.x + self.y + self.z
    
class FerrisWheel(Exhibit):
    z = 'do'
    def __init__(self, x):
        self.x = x
        self.y = 'l'

class Carousel(Exhibit):
    x = 'Wa'

def exhibit_demos():
    """
    >>> Exhibit('a', 'b').get_name()
    'ab!'
    >>> FerrisWheel('c').get_name()
    'cldo'
    >>>
    >>> Carousel('d', 'e').get_name()
    'de!'
    """
    return

# Accounts

class Account:
    """An account has a balance and a holder.

    >>> a = Account('John')
    >>> a.holder
    'John'
    >>> a.deposit(100)
    100
    >>> a.withdraw(90)
    10
    >>> a.withdraw(90)
    'Insufficient funds'
    >>> a.balance
    10
    >>> a.interest
    0.02
    """

    interest = 0.02  # A class attribute

    def __init__(self, account_holder):
        self.holder = account_holder
        self.balance = 0

    def deposit(self, amount):
        """Add amount to balance."""
        self.balance = self.balance + amount
        return self.balance

    def withdraw(self, amount):
        """Subtract amount from balance if funds are available."""
        if amount > self.balance:
            return 'Insufficient funds'
        self.balance = self.balance - amount
        return self.balance


class CheckingAccount(Account):
    """A bank account that charges for withdrawals.

    >>> ch = CheckingAccount('Jack')
    >>> ch.balance = 20
    >>> ch.withdraw(5)
    14
    >>> ch.interest
    0.01
    """

    withdraw_fee = 1
    interest = 0.01

    def withdraw(self, amount):
        return Account.withdraw(self, amount + self.withdraw_fee)
        # Alternatively:
        return super().withdraw(amount + self.withdraw_fee)

