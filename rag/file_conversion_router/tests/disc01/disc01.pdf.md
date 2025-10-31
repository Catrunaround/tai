# While and If

Learning to use if and while is an essential skill. During this discussion, focus on what we’ve studied in the first three lectures: if, while, assignment $( = )$ , comparison $( < , > , = = , \ \ldots )$ , and arithmetic. Please don’t use features of Python that we haven’t discussed in class yet, such as for, range, and lists. We’ll have plenty of time for those later in the course, but now is the time to practice the use of if (textbook section 1.5.4) and while (textbook section 1.5.5).

# Q1: Race

The race function below sometimes returns the wrong value and sometimes runs forever.

def race(x, y): """The tortoise always walks x feet per minute, while the hare repeatedly runs y feet per minute for 5 minutes, then rests for 5 minutes. Return how many minutes pass until the tortoise first catches up to the hare. $> > >$ race(5, 7) # After 7 minutes, both have gone 35 steps 7 $> > >$ race(2, 4) # After 10 minutes, both have gone 20 steps 10 """ assert $\texttt { y } > \texttt { x }$ and $\texttt { y } < = \texttt { 2 } * \texttt { x }$ , 'the hare must be fast but not too fast' tortoise, hare, minutes $\qquad = \ 0$ , 0, 0 while minutes $\scriptstyle = = 0$ or tortoise - hare: tortoise $+ = \texttt { x }$ if minutes $\% 1 0 < 5$ : hare += y minutes += 1 return minutes

Find positive integers $\mathtt { x }$ and $\mathtt { y }$ (with $\mathtt { y }$ larger than $\mathbf { x }$ but not larger than $2 \texttt { * * }$ ) for which either: - race(x, y) returns the wrong value or - $\mathtt { r a c e ( x , \ y ) }$ runs forever

You just need to find one pair of numbers that satisfies either of these conditions to finish the question, but if you want to think of more you can.

Notes: - $\texttt { x } + = \texttt { 1 }$ is the same as $\textbf { z } = \textbf { x } + \textbf { 1 }$ when $\mathbf { x }$ is assigned to a number. - 0 is a false value and all other numbers are true values.

# Q2: Fizzbuzz

Implement the classic $F i z z B u z z$ sequence. The fizzbuzz function takes a positive integer $\mathbf { n }$ and prints out a single line for each integer from 1 to n. For each i:

• If i is divisible by both 3 and 5, print fizzbuzz.   
• If i is divisible by 3 (but not 5), print fizz.   
• If i is divisible by 5 (but not 3), print buzz.   
• Otherwise, print the number i.

Try to make your implementation of fizzbuzz concise.

<table><tr><td>def fizzbuzz(n): &quot;I I &quot;</td></tr><tr><td>&gt;&gt;&gt; result = fizzbuzz(16)</td></tr><tr><td>1</td></tr><tr><td>2</td></tr><tr><td>fizz</td></tr><tr><td>4</td></tr><tr><td>buzz</td></tr><tr><td>fizz</td></tr><tr><td>7 8</td></tr><tr><td>fizz</td></tr><tr><td>buzz</td></tr><tr><td>11</td></tr><tr><td>fizz</td></tr><tr><td>13</td></tr><tr><td>14</td></tr><tr><td>fizzbuzz</td></tr><tr><td>16</td></tr><tr><td>&gt;&gt;&gt; print(result)</td></tr><tr><td>None II I I</td></tr><tr><td>&quot;*** YOUR CODE HERE ***&quot;</td></tr><tr><td></td></tr></table>

# Problem Solving

A useful approach to implementing a function is to: 1. Pick an example input and corresponding output. 2. Describe a process (in English) that computes the output from the input using simple steps. 3. Figure out what additional names you’ll need to carry out this process. 4. Implement the process in code using those additional names. 5. Determine whether the implementation really works on your original example. 6. Determine whether the implementation really works on other examples. (If not, you might need to revise step 2.)

Importantly, this approach doesn’t go straight from reading a question to writing code.

For example, in the is_prime problem below, you could: 1. Pick n is 9 as the input and False as the output. 2. Here’s a process: Check that 9 (n) is not a multiple of any integers between 1 and 9 (n). 3. Introduce i to represent each number between 1 and 9 (n). 4. Implement is_prime (you get to do this part with your group). 5. Check that is_prime(9) will return False by thinking through the execution of the code. 6. Check that is_prime(3) will return True and is_prime(1) will return False.

Try this approach together on the next two problems.

Important: It’s highly recommended that you don’t check your work using a computer right away. Instead, talk to your group and think to try to figure out if an answer is correct. On exams, you won’t be able to guess and check because you won’t have a Python interpreter. Now is a great time to practice checking your work by thinking through examples.

# Q3: Is Prime?

Write a function that returns True if a positive integer n is a prime number and False otherwise.

A prime number n is a number that is not divisible by any numbers other than 1 and n itself. For example, 13 is prime, since it is only divisible by 1 and 13, but 14 is not, since it is divisible by 1, 2, 7, and 14.

Use the $\%$ operator: x % y returns the remainder of $\mathtt { x }$ when divided by y.

<table><tr><td>def is_prime(n):</td></tr><tr><td>II II &quot;</td></tr><tr><td>&gt;&gt;&gt; is_prime(10)</td></tr><tr><td>False</td></tr><tr><td>&gt;&gt;&gt; is_prime(7)</td></tr><tr><td>True</td></tr><tr><td>&gt;&gt; is_prime(1) # one is not a prime number!!</td></tr><tr><td>False</td></tr><tr><td>&quot; I &quot;*** YOUR CODE HERE ***&quot;</td></tr></table>

# Q4: Unique Digits

Write a function that returns the number of unique digits in a positive integer.

Hints: You can use // and $\%$ to separate a positive integer into its one’s digit and the rest of its digits.

You may find it helpful to first define a function has_digit(n, k), which determines whether a number n has digit k.

<table><tr><td>def unique_digits(n): &quot;&quot;&quot;Return the number of unique digits in positive integer n.</td></tr><tr><td></td></tr><tr><td>&gt;&gt;&gt; unique_digits(8675309) # All are unique 7</td></tr><tr><td>&gt;&gt; unique_digits(13173131) # 1, 3, and 7 3</td></tr><tr><td>&gt;&gt;&gt; unique_digits(101) # 0 and 1 2</td></tr><tr><td>II  &quot;I</td></tr><tr><td>&quot;*** YOUR CODE HERE ***&quot;</td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td></td></tr><tr><td>def has_digit(n, k):</td></tr><tr><td>&quot;&quot;&quot;Returns whether k is a digit in n.</td></tr><tr><td></td></tr><tr><td>&gt;&gt;&gt; has_digit(10, 1)</td></tr><tr><td></td></tr><tr><td>True</td></tr><tr><td>&gt;&gt;&gt; has_digit(12, 7)</td></tr><tr><td></td></tr><tr><td>False</td></tr><tr><td></td></tr><tr><td>II I &quot;I</td></tr><tr><td>assert k &gt;= 0 and k &lt; 10</td></tr></table>

# Q5: Ordered Digits

Implement the function ordered_digits, which takes as input a positive integer and returns True if its digits, read left to right, are in non-decreasing order, and False otherwise. For example, the digits of 5, 11, 127, 1357 are ordered, but not those of 21 or 1375.

<table><tr><td>def ordered_digits(x): &quot;&quot;&quot;Return True if the (base 10) digits of X&gt;0 are in non-decreasing</td></tr></table>