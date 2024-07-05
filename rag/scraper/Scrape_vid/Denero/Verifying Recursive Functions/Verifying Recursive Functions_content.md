# "The Recursive Leap of Faith: Verifying the Correctness of Recursive Functions"

##  Next we'll talk about verifying the correctness of a recursive function. And that requires the recursive leap of faith. There's my friend Kevin sitting on top of a very large cliff. And that's what it can feel like when you write down a recursive function. So here's factorial. Now it's easy to see that factorial is going to work when n is zero because it just doesn't think simple. It returns one. But how do we really know that in any other case this thing is actually going to work? Well here's a strategy. Ask yourself if fact is implemented correctly through the following steps. First verify the base cases. That just makes your life easy because you know that you have some cases correct. So if n is zero this thing behaves correctly. Next you have to treat fact as a functional abstraction. What that means is for this call to fact don't think about how it's implemented. Just think about what it's supposed to do. So its correct behavior is to return n minus 1 factorial. That's abstracting away the details of its implementation. So we assume that fact n minus 1 does in fact return n minus 1 factorial. Then we can verify that n factorial is correct by assuming that n minus 1 factorial is computed correctly and knowing that the result n factorial is n times n minus 1 factorial. So for a particular value of n we can do this verification process. Does this compute 4 factorial correctly? Well is 4 factorial 4 times 3 factorial? Yes it is. It's 24 which is 4 times 6. Generally we assume that a function is correctly defined for the simpler case that we use in our recursive call and then verify that if that's the case then the whole thing is correctly defined for the problem that we stick. So we assume that it works correctly for n minus 1 and we show that therefore it works correctly for n.
